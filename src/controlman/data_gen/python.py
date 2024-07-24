# Standard libraries
import re as _re

# Non-standard libraries
from packaging import specifiers as _specifiers

from versionman import PEP440SemVer as _PEP440SemVer
import pylinks
import trove_classifiers as _trove_classifiers
from loggerman import logger as _logger

from controlman import exception as _exception
from controlman.nested_dict import NestedDict as _NestedDict
from controlman.center_man.cache import CacheManager
from controlman.protocol import Git as _Git


class PythonDataGenerator:

    def __init__(
        self,
        data: _NestedDict,
        git_manager: _Git,
        cache: CacheManager,
        github_api: pylinks.api.GitHub,
        data_main: _NestedDict | None = None,
        future_versions: dict[str, str | _PEP440SemVer] | None = None,
    ):
        self._data = data
        self._git = git_manager
        self._cache = cache
        self._github_api = github_api
        self._data_main = data_main
        self._future_vers = future_versions or {}
        return

    def generate(self):
        self._package_name()
        self._package_python_versions()
        self._package_operating_systems()
        self.trove_classifiers()
        return

    @_logger.sectioner("Package Name")
    def _package_name(self) -> None:
        for path in ("pkg.name", "testsuite.name"):
            name = self._data.fill(path)
            if name:
                name_cleaned = _re.sub(r'[^a-zA-Z0-9._-]', '-', name)
                self._data[path] = _re.sub(r'^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$', '', name_cleaned)
        for path in ("pkg.import_name", "testsuite.import_name"):
            import_name = self._data.fill(path)
            if import_name:
                import_name_cleaned = _re.sub(r'[^a-zA-Z0-9]', '_', import_name.lower())
                self._data[path] = _re.sub(r'^[0-9]+', "", import_name_cleaned)
        return

    @_logger.sectioner("Package Python Versions")
    def _package_python_versions(self) -> dict:

        def get_python_releases():
            release_versions = self._cache.get("python", "releases")
            if release_versions:
                return release_versions
            _logger.info("Get Python versions from GitHub API")
            release_versions = self._github_api.user("python").repo("cpython").semantic_versions(tag_prefix="v")
            live_versions = []
            for version in release_versions:
                version_tuple = tuple(map(int, version.split(".")))
                if version_tuple[0] < 2:
                    continue
                if version_tuple[0] == 2 and version_tuple[1] < 3:
                    continue
                live_versions.append(version_tuple)
            live_versions = sorted(live_versions, key=lambda x: tuple(map(int, x.split("."))))
            self._cache.set("python", "releases", live_versions)
            return live_versions

        version_spec_key = "pkg.python.version.spec"
        spec_str = self._data.fill(version_spec_key)
        if not spec_str:
            _exception.ControlManSchemaValidationError(
                "The package has not specified a Python version specifier.",
                key=version_spec_key,
            )
        try:
            spec = _specifiers.SpecifierSet(spec_str)
        except _specifiers.InvalidSpecifier as e:
            raise _exception.ControlManSchemaValidationError(
                f"Invalid Python version specifier '{spec_str}'.",
                key=version_spec_key,
            ) from e

        current_python_versions = get_python_releases()
        micro_str = []
        micro_int = []
        minor_str = []
        minor_int = []
        minor_str_pyxy = []
        for compat_ver_micro_str in spec.filter(current_python_versions):
            micro_str.append(compat_ver_micro_str)
            compat_ver_micro_int = tuple(map(int, compat_ver_micro_str.split(".")))
            micro_int.append(compat_ver_micro_int)
            compat_ver_minor_str = ".".join(map(str, compat_ver_micro_int[:2]))
            if compat_ver_minor_str in minor_str:
                continue
            minor_str.append(compat_ver_minor_str)
            minor_int.append(compat_ver_micro_int[:2])
            minor_str_pyxy.append(f"py{''.join(map(str, compat_ver_micro_int[:2]))}")

        if len(micro_str) == 0:
            raise _exception.ControlManSchemaValidationError(
                f"The Python version specifier '{spec_str}' does not match any "
                f"released Python version: '{current_python_versions}'.",
                key=version_spec_key,
            )
        output = {
            "micros": sorted(micro_str, key=lambda x: tuple(map(int, x.split(".")))),
            "minors": sorted(minor_str, key=lambda x: tuple(map(int, x.split(".")))),
            "pyxy": sorted(minor_str_pyxy),
        }
        self._data["pkg.python.version"].update(output)
        if self._data["test"]:
            self._data["test.python.version.spec"] = spec_str
        _logger.debug(f"Generated data: {str(output)}")
        return output

    @_logger.sectioner("Package Operating Systems")
    def _package_operating_systems(self):
        data_os = self._data.fill("pkg.os")
        if not isinstance(data_os, dict):
            raise _exception.ControlManSchemaValidationError(
                "The package has not specified any operating systems.",
                key="pkg.os",
            )
        pure_python = not any("ci_build" in os for os in data_os.values())
        self._data["pkg.python.pure"] = pure_python
        self._data["pkg.os.independent"] = len(data_os) == 3 and pure_python
        return

    def trove_classifiers(self):

        def programming_language() -> list[str]:
            template = "Programming Language :: Python :: {}"
            classifiers = []
            has_2 = False
            has_3 = False
            for version in self._data["pkg.py_version.minors"]:
                if version.startswith("2"):
                    has_2 = True
                if version.startswith("3"):
                    has_3 = True
                classifiers.append(template.format(version))
            if has_2 and not has_3:
                classifiers.append(template.format("2 :: Only"))
            elif has_3 and not has_2:
                classifiers.append(template.format("3 :: Only"))
            return classifiers

        def operating_system():
            template = "Operating System :: {}"
            postfix = {
                "windows": "Microsoft :: Windows",
                "macos": "MacOS",
                "linux": "POSIX :: Linux",
            }
            data_os = self._data["pkg.os"]
            has_build_info = any("ci_build" in os for os in data_os.values())
            if not has_build_info and len(data_os) == 3:
                return [template.format("OS Independent")]
            return [template.format(postfix[os_name]) for os_name in data_os]

        common_classifiers = programming_language()
        common_classifiers.extend(operating_system())
        if self._data["license.trove"]:
            common_classifiers.append(self._data["license.trove"])
        # common_classifiers.append(self._package_development_status())
        if self._data["pkg.typed"]:
            common_classifiers.append("Typing :: Typed")
        for common_classifier in common_classifiers:
            if common_classifier not in _trove_classifiers.classifiers:
                raise RuntimeError(
                    f"Auto-generated trove classifier '{common_classifier}' is not valid. "
                    "Please file an issue ticket at https://github.com/RepoDynamics/ControlMan."
                )
        for path in ("pkg", "test"):
            classifiers = self._data.get(f"{path}.classifiers", [])
            for classifier in classifiers:
                if classifier not in _trove_classifiers.classifiers:
                    raise _exception.ControlManSchemaValidationError(
                        f"Trove classifier '{classifier}' is not valid.",
                        key=f"{path}.classifiers"
                    )
            classifiers.extend(common_classifiers)
            self._data[f"{path}.classifiers"] = sorted(classifiers)
        return

    def _package_development_status(self) -> dict:
        curr_branch, _ = self._git.get_all_branch_names()
        future_ver = self._future_vers.get(curr_branch)
        if future_ver:
            ver = _PEP440SemVer(str(future_ver))
        else:
            tag_prefix = self._data_main.fill("tag.version.prefix")
            if not tag_prefix:
                return
            ver = self._git.get_latest_version(tag_prefix=ver_tag_prefix)
        if not ver:
            _logger.warning(f"Failed to get latest version from branch '{branch}'; skipping branch.")
            continue
        if branch == curr_branch:
            branch_metadata = self._data
        elif branch == main_branch:


        phase = {
            1: "Planning",
            2: "Pre-Alpha",
            3: "Alpha",
            4: "Beta",
            5: "Production/Stable",
            6: "Mature",
            7: "Inactive",
        }
        output = {
            "dev_phase": phase[status_code],
            "trove_classifier": f"Development Status :: {status_code} - {phase[status_code]}",
        }
        _logger.info(f"Development info: {output}")
        _logger.section_end()
        return output