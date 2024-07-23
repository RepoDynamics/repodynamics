from controlman.datatype import DynamicFile
from controlman.file_gen.package.python import PythonPackageFileGenerator
from controlman import ControlCenterContentManager
from controlman._path_manager import PathManager


def generate(
    content_manager: ControlCenterContentManager,
    path_manager: PathManager,
) -> list[tuple[DynamicFile, str]]:
    if content_manager["package"]["type"] == "python":
        return PythonPackageFileGenerator(
            data=content_manager, path_manager=path_manager
        ).generate()
    else:
        return []
