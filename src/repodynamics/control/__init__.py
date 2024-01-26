from typing import Literal, Optional, Sequence, Callable
from pathlib import Path
import json

from repodynamics.logger import Logger
from repodynamics.control.generator import MetadataGenerator
from repodynamics.control.manager import MetaManager
from repodynamics.control.reader import MetaReader
from repodynamics.control.validator import MetaValidator
from repodynamics.control import files
from repodynamics.path import RelativePath
from repodynamics.control.writer import MetaWriter
from repodynamics.git import Git
from repodynamics import file_io


def read_from_json_file(
    path_root: str | Path = ".", commit_hash: str = "", git: Git | None = None, logger: Logger | None = None
) -> MetaManager | None:
    logger = logger or Logger()
    path_root = Path(path_root).resolve()
    if commit_hash:
        git = git or Git(path_repo=path_root)
        content = git.file_at_hash(
            commit_hash=commit_hash,
            path=RelativePath.file_metadata,
            raise_missing=False,
        )
        return read_from_json_string(content=content, logger=logger) if content else None
    path_json = path_root / RelativePath.file_metadata
    metadata = file_io.read_datafile(path_data=path_json)  # TODO: add logging and error handling
    if not metadata:
        return None
    meta_manager = MetaManager(options=metadata)
    MetaValidator(metadata=meta_manager, logger=logger).validate()
    return meta_manager


def read_from_json_string(content: str, logger: Logger | None = None) -> MetaManager:
    logger = logger or Logger()
    metadata = json.loads(content)
    meta_manager = MetaManager(options=metadata)
    MetaValidator(metadata=meta_manager, logger=logger).validate()
    return meta_manager
