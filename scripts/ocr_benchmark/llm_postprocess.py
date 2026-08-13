#!/usr/bin/env python3
"""Псевдо-движок `tesseract+llm`: постранично чинит явные OCR-артефакты через LLM.

Не переиспользует уже сохранённый `tesseract.raw.txt` из run_ocr.py — тот склеен по страницам
через "\n\n" без сохранения границ, а для LLM-чанкинга нужны именно постраничные куски (см.
план, §2: контекстное окно + ограничение зоны поражения модели одной страницей). Вместо этого
рестерирует страницы тем же способом (`dpi=200`) и гоняет TesseractEngine повторно — OCR
детерминирован, результат идентичен уже сохранённому `tesseract.raw.txt`, повторный проход
стоит времени, но не корректности.

Промпт запрещает менять числа/даты/номера статей-пунктов-частей/суммы и явно перечисляет
защищённые фрагменты (`extract_critical_elements` на исходной OCR-странице), чтобы модель не
угадывала сама, что является числом — это первый, «мягкий» слой защиты и он не идеален (LLM
может проигнорировать инструкцию).

Второй, «жёсткий» слой — после ответа LLM критичные элементы страницы сравниваются до/после
(critical_elements.py); если хоть один пропал или исказился, правка этой страницы целиком
ОТКАТЫВАЕТСЯ к исходному OCR-варианту, а не просто помечается флагом. Это гарантирует, что в
финальный `<engine>.raw.txt` никогда не попадёт страница с искажённым критичным элементом —
промпт-запрет сам по себе, как показал первый прогон бенчмарка (9/15 документов), ненадёжен.
Диагностика при этом не теряется: `ocr_altered_critical_path` фиксирует, что модель хотя бы
один раз попыталась нарушить запрет (до отката), `ocr_llm_reverted_pages_path` — сколько именно
страниц документа откачено.

Отдельно обнаружен и обработан инфраструктурный дефект: используемый в этом окружении
Kafka-клиент (`LLM_TRANSPORT=kafka`) под пачкой быстрых запросов подряд иногда отвечает
status="ok" с пустым текстом вместо ошибки — не отличить от «модель ничего не поправила» без
явной проверки. `_call_with_retries` ретраит такой ответ с задержкой и логирует каждую пустую
попытку (не проглатывает молча), а троттлинг между страницами (`_INTER_PAGE_DELAY_SECONDS`)
снижает саму частоту деградации воркера под нагрузкой.
"""

import argparse
import logging
import re
import time

from common import (
    fetch_pdf_bytes,
    included_manifest,
    ocr_altered_critical_path,
    ocr_cleaned_path,
    ocr_llm_reverted_pages_path,
    ocr_raw_path,
)

import fitz

from explainlaw.extraction.critical_elements import compare_critical_elements, extract_critical_elements
from explainlaw.extraction.ocr_engines import TesseractEngine
from explainlaw.gates.text_checks import reflow_soft_linebreaks, strip_signature_block
from explainlaw.llm.factory import create_gateway_client, create_qwen_client
from explainlaw.storage.object_store import get_storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("llm_postprocess")

PAGE_LOG_EVERY = 10
PSEUDO_ENGINE_NAME = "tesseract+llm"

_SYSTEM_PROMPT_TEMPLATE = """Ты корректор текста, полученного OCR-распознаванием скана федерального закона.

Правь ТОЛЬКО явные артефакты распознавания в обычных словах: разорванные посередине слова,
спутанные похожие символы («0»/«О», «1»/«l»/«I», «rn»/«m» и подобные), одиночный мусор от
качества скана (обрывки символов, не образующие слов).

ЗАЩИЩЁННЫЕ ФРАГМЕНТЫ этой страницы — ниже дословные фрагменты текста (числа, даты, ссылки на
статьи/пункты/части, суммы, проценты), которые уже извлечены отдельным алгоритмом. Каждый из
них должен присутствовать в твоём ответе БАЙТ-В-БАЙТ так же, как здесь, без единого изменения —
даже если тебе кажется, что в нём ошибка OCR (дата не бьётся с соседним годом, номер статьи
выглядит нелогично, лишний/пропущенный ноль). Ты НЕ можешь надёжно понять из одной страницы,
какое значение верное — не гадай и не «исправляй» его. Если правка обычного текста рядом
случайно задевает такой фрагмент — не делай эту правку вообще, оставь всю строку как есть:
{protected_spans}

ЗАПРЕЩЕНО в любом случае, даже для фрагментов вне списка выше:
- менять числа, даты, номера статей/пунктов/частей/подпунктов, денежные суммы, проценты;
- добавлять, убирать или пересказывать смысл;
- переводить, сокращать, комментировать или оформлять markdown.

Верни ИСКЛЮЧИТЕЛЬНО исправленный текст страницы целиком, без пояснений."""

_NO_PROTECTED_SPANS = "(на этой странице защищённых фрагментов не обнаружено)"


def _clean(raw: str) -> str:
    return strip_signature_block(reflow_soft_linebreaks(raw))


def _format_protected_spans(page_text: str) -> str:
    items = extract_critical_elements(page_text).all_items()
    if not items:
        return _NO_PROTECTED_SPANS
    seen: set[str] = set()
    lines: list[str] = []
    for _category, item in items:
        if item and item not in seen:
            seen.add(item)
            lines.append(f"- «{item}»")
    return "\n".join(lines) if lines else _NO_PROTECTED_SPANS


_EMPTY_RESPONSE_ATTEMPTS = 3
_EMPTY_RESPONSE_BACKOFF_SECONDS = 4.0
_INTER_PAGE_DELAY_SECONDS = 1.0

# Наблюдалось в реальном ответе воркера: строка "/no_think" (управляющий тег Qwen3
# chat-template для отключения reasoning) попала в текст ответа вместо того, чтобы быть
# обработанной сервером — не критичный элемент, поэтому safety-net его не ловит, а CER/WER
# он бы исказил как лишний "мусорный" токен, которого нет в эталоне.
_CONTROL_TOKEN_RE = re.compile(r"[ \t]*/(?:no_)?think\s*$")


def _strip_control_tokens(text: str) -> str:
    return _CONTROL_TOKEN_RE.sub("", text)


def _call_with_retries(client, *, label: str, system_prompt: str, page_text: str) -> str | None:
    """Гонит client.chat с ретраями на пустой ответ.

    Обнаружен воркер (Kafka/Qwen), который под нагрузкой пачки быстрых запросов подряд отвечает
    status="ok" с пустым текстом вместо ошибки — client.chat() в этом случае молча возвращает ""
    без исключения. Не отличить такой ответ от «модель ничего не поправила» нельзя иначе, кроме
    как через явный ретрай с задержкой и логирование каждой пустой попытки.
    """
    for attempt in range(1, _EMPTY_RESPONSE_ATTEMPTS + 1):
        try:
            result = client.chat(system=system_prompt, user=page_text, temperature=0.1)
            if result:
                result = _strip_control_tokens(result)
        except Exception:
            logger.exception("%s: попытка %d/%d упала с исключением", label, attempt, _EMPTY_RESPONSE_ATTEMPTS)
            result = None

        if result and result.strip():
            return result

        logger.warning(
            "%s: попытка %d/%d вернула пустой ответ (воркер перегружен или деградировал под нагрузкой)",
            label,
            attempt,
            _EMPTY_RESPONSE_ATTEMPTS,
        )
        if attempt < _EMPTY_RESPONSE_ATTEMPTS:
            time.sleep(_EMPTY_RESPONSE_BACKOFF_SECONDS)

    return None


def _llm_clean_page(page_text: str) -> tuple[str, bool]:
    """Возвращает (текст, llm_succeeded).

    llm_succeeded=False означает, что ни один доступный клиент не вернул пригодный (непустой)
    ответ после ретраев — использован исходный OCR-текст страницы без правок, и это отдельно
    залогировано выше как явное предупреждение, а не тихо проглочено.
    """
    if not page_text.strip():
        return page_text, True

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(protected_spans=_format_protected_spans(page_text))

    client = create_gateway_client()
    if client.available:
        result = _call_with_retries(client, label="gateway", system_prompt=system_prompt, page_text=page_text)
        if result is not None:
            return result, True

    qwen = create_qwen_client()
    if qwen.available:
        result = _call_with_retries(qwen, label="qwen", system_prompt=system_prompt, page_text=page_text)
        if result is not None:
            return result, True

    return page_text, False


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM-постобработка OCR (псевдо-движок tesseract+llm)")
    parser.add_argument("--eo", action="append", help="Ограничить конкретными eo_number (можно несколько раз)")
    parser.add_argument("--force", action="store_true", help="Перегнать даже если raw.txt уже существует")
    args = parser.parse_args()

    candidates = included_manifest()
    if args.eo:
        wanted = set(args.eo)
        candidates = [c for c in candidates if c.eo_number in wanted]
    if not candidates:
        logger.error("Пустая выборка (sample_manifest.csv с include=true, либо --eo не совпал)")
        return 1

    engine = TesseractEngine()
    if not engine.available():
        logger.error("Tesseract недоступен в этом окружении")
        return 1

    storage = get_storage()
    stats = {
        "documents": 0,
        "pages": 0,
        "intercepted_docs": 0,
        "reverted_pages": 0,
        "empty_llm_pages": 0,
        "errors": 0,
    }

    for candidate in candidates:
        stats["documents"] += 1
        raw_path = ocr_raw_path(candidate.eo_number, PSEUDO_ENGINE_NAME)
        if raw_path.exists() and not args.force:
            logger.info("skip %s (уже есть)", candidate.eo_number)
            continue

        pdf_bytes = fetch_pdf_bytes(storage, candidate)
        fitz_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_chunks: list[str] = []
        intercepted_this_doc = False
        reverted_pages_this_doc = 0
        try:
            total = fitz_doc.page_count
            logger.info("LLM-постобработка %s [%s] (%d стр.)", candidate.eo_number, candidate.number, total)
            for idx, page in enumerate(fitz_doc, start=1):
                pix = page.get_pixmap(dpi=200)
                ocr_text = engine.image_to_text(pix.tobytes("jpeg")) or ""
                try:
                    llm_text, llm_ok = _llm_clean_page(ocr_text)
                except Exception:
                    logger.exception(
                        "LLM-правка стр. %d/%d документа %s упала — оставляю OCR без правок",
                        idx,
                        total,
                        candidate.eo_number,
                    )
                    llm_text = ocr_text
                    llm_ok = False
                    stats["errors"] += 1

                if not llm_ok:
                    stats["empty_llm_pages"] += 1

                comparison = compare_critical_elements(ocr_text, llm_text)
                if comparison.missing:
                    intercepted_this_doc = True
                    reverted_pages_this_doc += 1
                    logger.warning(
                        "  критичные элементы изменились на стр. %d/%d документа %s: %s — откат страницы к OCR",
                        idx,
                        total,
                        candidate.eo_number,
                        comparison.missing,
                    )
                    llm_text = ocr_text  # жёсткий откат: правка с искажённым критичным элементом не публикуется

                page_chunks.append(llm_text)
                stats["pages"] += 1
                time.sleep(_INTER_PAGE_DELAY_SECONDS)  # троттлинг: не бомбить воркер пачкой запросов подряд
                if idx % PAGE_LOG_EVERY == 0 or idx == total:
                    logger.info("  %s: стр. %d/%d", candidate.eo_number, idx, total)
        finally:
            fitz_doc.close()

        raw_text = "\n\n".join(page_chunks)
        raw_path.write_text(raw_text, encoding="utf-8")
        ocr_cleaned_path(candidate.eo_number, PSEUDO_ENGINE_NAME).write_text(_clean(raw_text), encoding="utf-8")

        flag_path = ocr_altered_critical_path(candidate.eo_number, PSEUDO_ENGINE_NAME)
        if intercepted_this_doc:
            stats["intercepted_docs"] += 1
            stats["reverted_pages"] += reverted_pages_this_doc
            flag_path.write_text("1", encoding="utf-8")
        elif flag_path.exists():
            flag_path.unlink()

        reverted_path = ocr_llm_reverted_pages_path(candidate.eo_number, PSEUDO_ENGINE_NAME)
        if reverted_pages_this_doc:
            reverted_path.write_text(str(reverted_pages_this_doc), encoding="utf-8")
        elif reverted_path.exists():
            reverted_path.unlink()

    logger.info("Итого: %s", stats)
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
