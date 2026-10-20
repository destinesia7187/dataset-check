from __future__ import annotations

import asyncio
import hashlib
from email.message import Message
from pathlib import Path

from python_multipart.multipart import MultipartParser, parse_options_header

from .common import AppError


async def receive_upload(request, folder, settings, store):
    limits = settings.limits
    media, options = parse_options_header(request.headers.get("content-type", ""))
    boundary = options.get(b"boundary")
    if media != b"multipart/form-data" or not boundary or len(boundary) > 200:
        raise AppError("REQUEST_INVALID", "Expected multipart/form-data containing a CSV file", 422)
    total = 0
    fields = {}
    seen = set()
    current = {}
    state = {"file": None, "filename": None, "bytes": 0, "ended": False, "parts": 0}
    digest = hashlib.sha256()
    path = Path(folder) / "original.csv"

    def begin():
        state["parts"] += 1
        if state["parts"] > 3:
            raise AppError("REQUEST_INVALID", "Too many multipart parts", 422)
        current.clear()
        current.update(
            headers={}, field=bytearray(), value=bytearray(), header_size=0, data=bytearray()
        )

    def header_field(data, start, end):
        current["header_size"] += end - start
        if current["header_size"] > limits["max_multipart_part_header_bytes"]:
            raise AppError("REQUEST_INVALID", "The multipart header is too large", 422)
        current["field"].extend(data[start:end])

    def header_value(data, start, end):
        current["header_size"] += end - start
        if current["header_size"] > limits["max_multipart_part_header_bytes"]:
            raise AppError("REQUEST_INVALID", "The multipart header is too large", 422)
        current["value"].extend(data[start:end])

    def header_end():
        current["headers"][bytes(current["field"]).lower()] = bytes(current["value"])
        current["field"].clear()
        current["value"].clear()

    def headers_finished():
        disposition = current["headers"].get(b"content-disposition", b"")
        message = Message()
        message["content-disposition"] = disposition.decode("utf-8", "strict")
        name = message.get_param("name", header="content-disposition")
        if name not in {"file", "encoding", "delimiter"} or name in seen:
            raise AppError("REQUEST_INVALID", "Unknown or repeated multipart field", 422)
        seen.add(name)
        current["name"] = name
        if name == "file":
            filename = message.get_filename()
            if not filename:
                raise AppError("REQUEST_INVALID", "No file was provided", 422)
            filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
            if len(filename) > limits["max_filename_length_chars"] or any(
                ord(x) < 32 for x in filename
            ):
                raise AppError("REQUEST_INVALID", "Invalid filename", 422)
            if not filename.lower().endswith(".csv"):
                raise AppError("UNSUPPORTED_FILE_TYPE", "Only CSV files are supported", 415)
            state["filename"] = filename
            state["file"] = path.open("wb")
        elif message.get_filename() is not None:
            raise AppError("REQUEST_INVALID", "Only one file part named file is allowed", 422)

    def data_received(data, start, end):
        chunk = data[start:end]
        if current["name"] == "file":
            state["bytes"] += len(chunk)
            if state["bytes"] > limits["max_file_size_bytes"]:
                raise AppError("FILE_TOO_LARGE", "The CSV file exceeds the size limit", 413)
            store.check_space(len(chunk))
            digest.update(chunk)
            state["file"].write(chunk)
        else:
            current["data"].extend(chunk)
            if len(current["data"]) > limits["max_multipart_text_length_chars"] * 4:
                raise AppError("REQUEST_INVALID", "The multipart parameter is too long", 422)

    def part_end():
        if current["name"] == "file":
            state["file"].close()
            state["file"] = None
        else:
            text = current["data"].decode("utf-8", "strict")
            if len(text) > limits["max_multipart_text_length_chars"]:
                raise AppError("REQUEST_INVALID", "The multipart parameter is too long", 422)
            fields[current["name"]] = text

    def end():
        state["ended"] = True

    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": begin,
            "on_header_field": header_field,
            "on_header_value": header_value,
            "on_header_end": header_end,
            "on_headers_finished": headers_finished,
            "on_part_data": data_received,
            "on_part_end": part_end,
            "on_end": end,
        },
    )
    try:
        async with asyncio.timeout(limits["upload_timeout_seconds"]):
            async for chunk in request.stream():
                total += len(chunk)
                if total > limits["max_request_body_bytes"]:
                    raise AppError("FILE_TOO_LARGE", "The upload body exceeds the size limit", 413)
                parser.write(chunk)
            parser.finalize()
        if not state["ended"] or "file" not in seen:
            raise AppError("REQUEST_INVALID", "Incomplete multipart body or missing file", 422)
        encoding = fields.get("encoding", "utf-8")
        delimiter = fields.get("delimiter", "auto")
        if encoding not in {"utf-8", "windows-1251"} or delimiter not in {
            "auto",
            "comma",
            "semicolon",
            "tab",
        }:
            raise AppError("REQUEST_INVALID", "Unsupported encoding or delimiter", 422)
        return {
            "input": str(path),
            "filename": state["filename"],
            "sha256": digest.hexdigest(),
            "encoding": encoding,
            "delimiter": delimiter,
        }
    except TimeoutError:
        raise AppError("UPLOAD_TIMEOUT", "The file upload timed out", 408) from None
    except (UnicodeError, ValueError) as exc:
        raise AppError("REQUEST_INVALID", "Invalid multipart request", 422) from exc
    finally:
        if state["file"]:
            state["file"].close()
