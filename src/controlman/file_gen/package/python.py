"""Python Package File Generator"""

# Standard libraries
from typing import Literal
import re
import textwrap
from pathlib import Path as _Path

# Non-standard libraries
import pyserials
import pysyntax as _pysyntax
from loggerman import logger
import markitup as _miu

from controlman.datatype import DynamicFile_, GeneratedFile
from controlman import _util
from controlman.nested_dict import NestedDict as _NestedDict
from controlman import const as _const
from controlman.file_gen import unit as _unit


class PythonPackageFileGenerator:
    def __init__(
        self,
        data: _NestedDict,
        data_before: _NestedDict,
        repo_path: _Path,
    ):
        self._data = data
        self._data_before = data_before
        self._path_repo = repo_path
        self._type = None
        self._pkg: dict = {}
        self._pkg_before: dict = {}
        self._pyproj_tool: dict | str | None = None
        self._path_root: _Path | None = None
        self._path_src: _Path | None = None
        self._path_import: _Path | None = None
        self._path_root_before: _Path | None = None
        self._path_src_before: _Path | None = None
        self._path_import_before: _Path | None = None
        return

    def generate(self, typ: Literal["pkg", "test"], pyproject_tool_config: dict | str | None = None) -> list[GeneratedFile]:
        self._type = typ
        self._pkg = _NestedDict(self._data[typ])
        self._pkg_before = _NestedDict(self._data_before[typ] or {})
        self._path_root = _Path(self._data[f"{typ}.path.root"])
        self._path_src = self._path_root / self._data[f"{typ}.path.source"]
        self._path_import = self._path_src / self._pkg["import_name"]
        if self._data_before[f"{typ}.path"]:
            self._path_root_before = _Path(self._data_before[f"{typ}.path.root"])
            self._path_src_before = self._path_root_before / self._data_before[f"{typ}.path.source"]
            self._path_import_before = self._path_src_before / self._pkg_before["import_name"]
        return (
            self.requirements()
            + self.pyproject(pyproject_tool_config)
            + self.python_files()
            + self.typing_marker()
            + self.manifest()
        )

    def is_disabled(self, key: str):
        return not any(key in source for source in [self._pkg, self._pkg_before])

    @logger.sectioner("Generate Package PEP 561 Typing Marker")
    def typing_marker(self) -> list[GeneratedFile]:
        if self.is_disabled("typed"):
            return []
        file = GeneratedFile(
            type=DynamicFile_[f"{self._type.upper()}_TYPING_MARKER"],
            content=(
                "# PEP 561 marker file. See https://peps.python.org/pep-0561/\n"
                if self._pkg["typed"] else ""
            ),
            path=f"{self._pkg['path.import']}/{_const.FILENAME_PACKAGE_TYPING_MARKER}",
            path_before=f"{self._pkg_before['path.import']}/{_const.FILENAME_PACKAGE_TYPING_MARKER}" if self._pkg_before['path.import'] else None,
        )
        return [file]

    @logger.sectioner("Generate Package Requirements File")
    def requirements(self) -> list[GeneratedFile]:
        if self.is_disabled("dependency"):
            return []
        conda_env_file = {
            "type": DynamicFile_[f"{self._type.upper()}_ENV_CONDA"],
            "path": self._data[f"{self._type}.dependency.env.conda.path"],
            "path_before": self._data_before[f"{self._type}.dependency.env.conda.path"],
        }
        pip_env_file = {
            "type": DynamicFile_[f"{self._type.upper()}_ENV_PIP"],
            "path": self._data[f"{self._type}.dependency.env.pip.path"],
            "path_before": self._data_before[f"{self._type}.dependency.env.pip.path"],
        }
        if not self._data[f"{self._type}.dependency"]:
            return [GeneratedFile(**env_file) for env_file in (conda_env_file, pip_env_file)]
        dependencies = list(self._data.get(f"{self._type}.dependency.core", {}).values())
        for optional_dep_group in self._data.get(f"{self._type}.dependency.optional", {}).values():
            dependencies.extend(list(optional_dep_group["package"].values()))
        conda_env, pip_env, pip_full = _unit.create_environment_files(
            dependencies=dependencies,
            env_name=_miu.txt.slug(self._data[f"{self._type}.dependency.env.conda.name"]),
        )
        return [
            GeneratedFile(content=conda_env, **conda_env_file),
            GeneratedFile(content=pip_env if pip_full else "", **pip_env_file)
        ]

    @logger.sectioner("Generate Package and Test-Suite Source Files")
    def python_files(self) -> list[GeneratedFile]:
        # Generate import name mapping
        mapping = {}
        core_dep_before = self._pkg_before.get("dependency", {}).get("core", {})
        for core_dep_name, core_dep in self._pkg.get("dependency", {}).get("core", {}).items():
            if core_dep_name in core_dep_before and (
                core_dep["import_name"] != core_dep_before[core_dep_name]["import_name"]
            ):
                mapping[core_dep_before[core_dep_name]["import_name"]] = core_dep["import_name"]
        optional_dep_before = {}
        for opt_dep_group_before in self._pkg_before.get("dependency", {}).get("optional", {}).values():
            optional_dep_before |= opt_dep_group_before["package"]
        for opt_dep_name, opt_dep_group in self._pkg.get("dependency", {}).get("optional", {}).items():
            for opt_dep_name, opt_dep in opt_dep_group["package"].items():
                if opt_dep_name in optional_dep_before and (
                    opt_dep["import_name"] != optional_dep_before[opt_dep_name]["import_name"]
                ):
                    mapping[optional_dep_before[opt_dep_name]["import_name"]] = opt_dep["import_name"]
        if "import_name" in self._pkg_before and self._pkg["import_name"] != self._pkg_before["import_name"]:
            mapping[self._pkg_before["import_name"]] = self._pkg["import_name"]
        if self._type == "test":
            if self._data_before["pkg.import_name"] and self._data["pkg.import_name"] != self._data_before["pkg.import_name"]:
                mapping[self._data_before["pkg.import_name"]] = self._data["pkg.import_name"]
        # Get all file glob matches
        path_to_globs_map = {}
        abs_path = self._path_repo / (self._path_src_before or self._path_src)
        for file_glob, file_config in self._pkg.get("file", {}).items():
            for filepath_match in abs_path.glob(file_glob):
                path_to_globs_map.setdefault(filepath_match, []).append(file_config)
        if not (mapping or path_to_globs_map):
            return []
        # Process each file
        out = []
        for filepath in abs_path.glob("**/*.py"):
            file_content = filepath.read_text()
            if mapping:
                file_content = _pysyntax.modify.rename_imports(module_content=file_content, mapping=mapping)
            if filepath in path_to_globs_map:
                for matched_glob in path_to_globs_map[filepath]:
                    file_config = self._pkg["file"][matched_glob]
                    if "docstring" in file_config:
                        docstring_before = self._pkg_before.get("file", {}).get(matched_glob, {}).get("docstring")
                        if docstring_before != file_config["docstring"]:
                            file_content = self._update_docstring(
                                file_content,
                                file_config["docstring"],
                                docstring_before,
                            )
            out.append(
                GeneratedFile(
                    type=DynamicFile_[f"{self._type.upper()}_SOURCE"],
                    subtype=str(filepath.relative_to(self._path_src)).replace("/", "."),
                    content=file_content,
                    path=str(filepath.relative_to(self._path_repo)),
                    path_before=str(
                        self._path_src_before / filepath.relative_to(self._path_src_before)
                    ) if self._path_src_before else None,
                )
            )
        # if not test_package_dir.alt_paths:
        #     # test-suite package must be created
        #     for testsuite_filename in ["__init__.txt", "__main__.txt", "general_tests.txt"]:
        #         logger.section(f"Test-Suite File '{testsuite_filename}'")
        #         file_info = self._pathman.python_file(
        #             (test_package_dir.path / testsuite_filename).with_suffix(".py")
        #         )
        #         file_content = pyserials.update.templated_data_from_source(
        #             templated_data=_util.file.get_package_datafile(f"template/testsuite/{testsuite_filename}"),
        #             source_data=self._data.content.as_dict
        #         )
        #         out.append((file_info, file_content))
        #         logger.info(code_title="File info", code=str(file_info))
        #         logger.debug(code_title="File content", code=file_content)
        #         logger.section_end()
        return out

    @logger.sectioner("Generate Package __init__.py File")
    def _update_docstring(self, file_content: str, template: str, template_before: str) -> str:
        docstring_text = textwrap.fill(
            template.strip(),
            width=80,
            replace_whitespace=False,
        ).strip()
        pattern = re.compile(
            r'^((?:[\t ]*#.*\n|[\t ]*\n)*)"""((?:.|\n)*?)"""((?:[ \t]*#.*)?(?:\n|$))', re.MULTILINE
        )
        match = pattern.match(file_content)
        if not match:
            docstring = f'"""{docstring_text}\n"""  # noqa: D400\n'
            return f"{docstring}\n\n{file_content}".strip() + "\n"
        before, within, after = [text.strip() for text in match.groups()]
        if not template_before:
            within = f"{within}\n\n{docstring_text}".strip()
        else:
            docstring_text_before = textwrap.fill(
                template_before.strip(),
                width=80,
                replace_whitespace=False,
            ).strip()
            within = within.replace(docstring_text_before, docstring_text)
        return re.sub(pattern, f'{before}\n\n"""{within}\n"""  {after}'.strip(), file_content)

#         file_content = """__version_details__ = {"version": "0.0.0"}
# __version__ = __version_details__["version"]"""
#
#         file_content =
#         logger.info(code_title="File info", code=str(file_info))
#         logger.debug(code_title="File content", code=file_content)
#         return [(file_info, file_content)]

    @logger.sectioner("Generate Package Manifest File")
    def manifest(self) -> list[GeneratedFile]:
        if self.is_disabled("manifest"):
            return []
        file_content = "\n".join(self._pkg.get("manifest", []))
        logger.debug(code_title="File content", code=file_content)
        file = GeneratedFile(
            type=DynamicFile_[f"{self._type.upper()}_MANIFEST"],
            content=file_content,
            path=str(self._path_root / _const.FILENAME_PACKAGE_MANIFEST),
            path_before=str(self._path_root_before / _const.FILENAME_PACKAGE_MANIFEST) if self._path_root_before else None,
        )
        return [file]

    @logger.sectioner("Generate Package pyproject.toml File")
    def pyproject(self, tool_config: dict | str | None) -> list[GeneratedFile]:
        if tool_config:
            if isinstance(tool_config, str):
                tool_config = pyserials.read.toml_from_string(data=tool_config, as_dict=False)
            if not isinstance(tool_config, dict) or list(tool_config.keys()) != ["tool"]:
                raise ValueError("Invalid pyproject.toml tool configuration")
            tool_config["project"] = self.pyproject_project()
            tool_config["build-system"] = self.pyproject_build_system()
            for build_tool_name, build_tool_config in self._pkg["build"].get("tool", {}).items():
                tool_config[build_tool_name] = build_tool_config
            pyproject = tool_config
        else:
            pyproject = {
                "project": self.pyproject_project(),
                "build-system": self.pyproject_build_system(),
            }
            tool_config = self._pkg["build"].get("tool", {})
            if tool_config:
                pyproject["tool"] = tool_config
        file_content = pyserials.write.to_toml_string(data=pyproject, sort_keys=False)
        logger.debug(code_title="File content", code=file_content)
        file = GeneratedFile(
            type=DynamicFile_[f"{self._type.upper()}_PYPROJECT"],
            content=file_content,
            path=str(self._path_root / _const.FILENAME_PKG_PYPROJECT),
            path_before=str(self._path_root_before / _const.FILENAME_PKG_PYPROJECT) if self._path_root_before else None,
        )
        return [file]

    def pyproject_build_system(self) -> dict:
        data = {
            "requires": ("array", self._data[f"{self._type}.build.requires"]),
            "build-backend": ("str", self._data[f"{self._type}.build.backend"]),
        }
        return data

    def pyproject_project(self) -> dict:
        data = {
            "name": ("str", self._pkg["name"]),
            "description": ("str", self._data["title"]),
            "keywords": ("array", self._data["keywords"]),
            "classifiers": ("array", self._pkg["classifiers"]),
            "license": (
                "inline_table",
                {"file": self._data["license.path"]} if self._data["license.path"] else None,
            ),
            "urls": ("table", self._pkg["urls"]),
            "authors": ("array_of_inline_tables", self.pyproject_project_authors),
            "maintainers": ("array_of_inline_tables", self.pyproject_project_maintainers),
            "readme": ("str", self._pkg["readme.path"]),
            "requires-python": ("str", self._pkg["python.version.spec"]),
            "dependencies": ("array", self.pyproject_project_dependencies),
            "optional-dependencies": ("table_of_arrays", self.pyproject_project_optional_dependencies),
            "entry-points": ("table_of_tables", self.pyproject_project_entry_points),
            "gui-scripts": ("table", self.pyproject_project_gui_scripts),
            "scripts": ("table", self.pyproject_project_scripts),
            "dynamic": ("array", ["version"]),
        }
        project = {}
        for key, (dtype, val) in data.items():
            if val:
                project[key] = pyserials.format.to_toml_object(data=val, toml_type=dtype)
        return project

    @property
    def pyproject_project_authors(self) -> list[dict[str, str]]:
        authors = self._data["citation.authors"]
        if not authors:
            return []
        authors_list = []
        for author in authors:
            author_entry = {"name": author["name"]["full"]}
            if "email" in author:
                author_entry["email"] = author["email"]["id"]
            authors_list.append(author_entry)
        return authors_list

    @property
    def pyproject_project_maintainers(self) -> list[dict[str, str]]:

        def update_dict(maintainer, weight: int):
            for registered_maintainer in registered_maintainers:
                if registered_maintainer[0] == maintainer:
                    registered_maintainer[1] += weight
                    break
            else:
                registered_maintainers.append([maintainer, weight])
            return

        registered_maintainers = []

        for code_owners_entry in self._data.get("maintainer.code_owners.owners", []):
            for code_owners in code_owners_entry.values():
                for code_owner in code_owners:
                    update_dict(code_owner, 4)
        for maintainer_type, weight in (("issue", 3), ("discussion", 2)):
            for maintainers in self._data.get(f"maintainer.{maintainer_type}", {}).values():
                for maintainer in maintainers:
                    update_dict(maintainer, weight)
        for maintainer_type in ("security", "code_of_conduct", "support"):
            maintainer = self._data.get(f"maintainer.{maintainer_type}")
            if maintainer:
                update_dict(maintainer, 1)
        maintainers_list = []
        for maintainer in sorted(registered_maintainers, key=lambda x: x[1], reverse=True):
            maintainer_info = maintainer[0]
            maintainer_entry = {"name": maintainer_info["name"]["full"]}
            if "email" in maintainer_info:
                maintainer_entry["email"] = maintainer_info["email"]["id"]
            maintainers_list.append(maintainer_entry)
        return maintainers_list

    @property
    def pyproject_project_dependencies(self):
        deps = []
        for core_dep in self._pkg.get("dependency.core", {}).values():
            pip = core_dep.get("pip")
            if pip:
                deps.append(pip["spec"])
        return deps

    @property
    def pyproject_project_optional_dependencies(self):
        opt_deps = {}
        for opt_dep_group in self._pkg.get("dependency.optional", {}).values():
            opt_deps[opt_dep_group["name"]] = [dep["pip"]["spec"] for dep in opt_dep_group["package"].values()]
        return opt_deps

    @property
    def pyproject_project_scripts(self):
        return self._scripts(typ="cli")

    @property
    def pyproject_project_gui_scripts(self):
        return self._scripts(typ="gui")

    @property
    def pyproject_project_entry_points(self):
        entry_points = {}
        for entry_group in self._data.get(f"{self._type}.entry.api", {}).values():
            entry_group_out = {}
            for entry_point in entry_group["entry"].values():
                entry_group_out[entry_point["name"]] = entry_point["ref"]
            entry_points[entry_group["name"]] = entry_group_out
        return entry_points

    def _scripts(self, typ: Literal["cli", "gui"]) -> dict[str, str]:
        scripts = {}
        for entry in self._data.get(f"{self._type}.entry.{typ}", {}).values():
            scripts[entry["name"]] = entry["ref"]
        return scripts
