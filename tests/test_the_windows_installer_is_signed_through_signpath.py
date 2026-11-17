"""The Windows installer goes through SignPath on its way to a release.

SignPath Foundation signs Serpentine3D for free, on conditions: every signed
file carries an accurate product name and version, the artifact configuration
pins them, the project publishes a code signing policy, and a fork without
the credentials still builds. None of that runs on a developer's machine, and
a mistake in it only shows up as a failed signing request on release day, so
these tests read the files that drive it.

There is no YAML parser among the dependencies, so the workflow is read as
text, a step at a time.
"""
import importlib.util
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "packaging" / "windows"
CONFIG = WINDOWS / "signpath" / "windows-installer.xml"
WORKFLOW = ROOT / ".github" / "workflows" / "build-windows.yml"
ISS = WINDOWS / "installer.iss"
POLICY = ROOT / "docs" / "code-signing-policy.md"

NS = "{http://signpath.io/artifact-configuration/v1}"
REQUIRED_LINE = (
    "Free code signing provided by [SignPath.io](https://about.signpath.io/), "
    "certificate by [SignPath Foundation](https://signpath.org/)")


def _iss_define(name: str) -> str:
    match = re.search(rf'^#define {name} "([^"]*)"', ISS.read_text(), re.M)
    assert match, f"installer.iss no longer defines {name}"
    return match.group(1)


def _installer_name() -> str:
    match = re.search(r"^OutputBaseFilename=(.+)$", ISS.read_text(), re.M)
    assert match, "installer.iss no longer names its output"
    return match.group(1).strip() + ".exe"


def _steps() -> list[str]:
    """The build job's steps, each as the text of its own block."""
    text = WORKFLOW.read_text(encoding="utf-8")
    body = text.split("\n    steps:\n", 1)[1]
    return ["- " + s for s in re.split(r"\n      - ", "\n" + body)[1:]]


def _step(name: str) -> str:
    found = [s for s in _steps() if re.match(rf"- name: {re.escape(name)}\n", s)]
    assert len(found) == 1, f"expected one step named {name!r}, found {len(found)}"
    return found[0]


def _index(name: str) -> int:
    for i, s in enumerate(_steps()):
        if re.match(rf"- name: {re.escape(name)}\n", s):
            return i
    pytest.fail(f"no step named {name!r}")


def _input(step: str, key: str) -> str:
    match = re.search(rf"^\s+{re.escape(key)}: (.+)$", step, re.M)
    assert match, f"the step has no {key!r} input"
    return match.group(1).strip()


def _sign_step() -> str:
    signs = [s for s in _steps()
             if "signpath/github-action-submit-signing-request@" in s]
    assert len(signs) == 1, "expected exactly one SignPath signing step"
    return signs[0]


# -- the artifact configuration ---------------------------------------------

def test_the_artifact_configuration_is_a_zip_holding_the_installer():
    """upload-artifact zips what it uploads, so SignPath receives a zip."""
    root = ET.parse(CONFIG).getroot()
    assert root.tag == NS + "artifact-configuration"
    files = [el for el in root if el.tag != NS + "parameters"]
    assert [el.tag for el in files] == [NS + "zip-file"]
    inside = list(files[0])
    assert [el.tag for el in inside] == [NS + "pe-file"]
    assert inside[0].get("path") == _installer_name()
    assert [el.tag for el in inside[0]] == [NS + "authenticode-sign"]


def test_nothing_but_the_installer_is_signed():
    """The bundle's DLLs are Qt's, Python's and OpenCASCADE's; the
    Foundation does not allow signing someone else's binaries."""
    text = CONFIG.read_text(encoding="utf-8")
    assert text.count("<authenticode-sign") == 1
    assert "*" not in text, "a wildcard could sweep third-party files in"


def test_the_configuration_pins_the_installer_metadata():
    """The Foundation requires product name and version restrictions."""
    root = ET.parse(CONFIG).getroot()
    pe = root.find(f"{NS}zip-file/{NS}pe-file")
    assert pe.get("product-name") == _iss_define("AppName") == "Serpentine3D"
    assert pe.get("company-name") == _iss_define("AppPublisher")
    assert pe.get("product-version") == "${version}"
    params = {p.get("name"): p for p in root.find(f"{NS}parameters")}
    assert params["version"].get("required") == "true"


# -- the workflow -----------------------------------------------------------

def test_the_installer_is_uploaded_before_it_is_signed():
    upload = _step("Upload unsigned installer for signing")
    assert "uses: actions/upload-artifact@v4" in upload
    assert "id: upload-unsigned" in upload
    assert _input(upload, "path") == f"packaging/windows/Output/{_installer_name()}"
    assert _index("Upload unsigned installer for signing") < _steps().index(_sign_step())


def test_the_signing_request_names_this_project():
    sign = _sign_step()
    assert "signpath/github-action-submit-signing-request@v3" in sign
    assert _input(sign, "api-token") == "${{ secrets.SIGNPATH_API_TOKEN }}"
    assert _input(sign, "organization-id") == "${{ vars.SIGNPATH_ORGANIZATION_ID }}"
    assert _input(sign, "project-slug") == "Serpentine3D"
    assert _input(sign, "signing-policy-slug") == (
        "${{ vars.SIGNPATH_SIGNING_POLICY_SLUG || 'test-signing' }}")
    assert _input(sign, "artifact-configuration-slug") == CONFIG.stem
    assert _input(sign, "github-artifact-id") == (
        "${{ steps.upload-unsigned.outputs.artifact-id }}")
    assert _input(sign, "wait-for-completion") == "true"
    assert _input(sign, "output-artifact-directory") == "packaging/windows/Output/signed"


def test_no_organization_id_is_written_into_the_workflow():
    """It comes from a repository variable; a guessed one would be wrong."""
    guid = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    assert not re.search(guid, WORKFLOW.read_text(encoding="utf-8"))


def test_the_version_parameter_comes_from_pyproject():
    sign = _sign_step()
    assert re.search(
        r"parameters: \|\n\s+version: \$\{\{ toJSON\(steps\.version\.outputs\.version\) \}\}",
        sign)
    version = _step("Read the version from pyproject.toml")
    assert "id: version" in version
    assert "make_version_info.py --version" in version
    assert _index("Read the version from pyproject.toml") < _steps().index(sign)


def test_a_fork_without_the_credentials_builds_unsigned():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(
        r"SIGNPATH_ENABLED: \$\{\{ secrets\.SIGNPATH_API_TOKEN != '' && "
        r"vars\.SIGNPATH_ORGANIZATION_ID != '' \}\}", text)
    for step in ("Upload unsigned installer for signing",
                 "Use the signed installer"):
        assert "env.SIGNPATH_ENABLED == 'true'" in _step(step)
    assert "env.SIGNPATH_ENABLED == 'true'" in _sign_step()
    # and the build says so, rather than shipping unsigned in silence
    assert "::warning" in _step("Note an unsigned build")


def test_a_release_whose_installer_is_already_prepared_is_not_signed_again():
    """Each signing with the Foundation's certificate waits for a manual
    approval; signing a file the release will not use wastes one."""
    check = _step("Check the release for a prepared installer")
    assert "id: release" in check
    assert "prepared=" in check
    for step in ("Upload unsigned installer for signing", "Use the signed installer"):
        assert "steps.release.outputs.prepared != 'true'" in _step(step)
    assert "steps.release.outputs.prepared != 'true'" in _sign_step()


def test_the_signed_installer_is_what_gets_published():
    use = _step("Use the signed installer")
    assert "packaging/windows/Output/signed/" + _installer_name() in use
    assert "Get-AuthenticodeSignature" in use, "check the file came back signed"
    signed_at = _index("Use the signed installer")
    assert _steps().index(_sign_step()) < signed_at
    assert signed_at < _index("Upload installer artifact")
    assert signed_at < _index("Attach to release")
    assert (f"packaging/windows/Output/{_installer_name()}"
            in _step("Upload installer artifact"))


def test_the_signing_action_can_read_the_uploaded_artifact():
    """A permissions block drops everything it does not list, and the action
    downloads the artifact with the job's token."""
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    assert re.search(r"^\s+actions: read", block, re.M)
    assert re.search(r"^\s+contents: write", block, re.M)


# -- version metadata -------------------------------------------------------

def _make_version_info():
    path = WINDOWS / "make_version_info.py"
    spec = importlib.util.spec_from_file_location("make_version_info", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_exe_version_is_read_from_pyproject(tmp_path, monkeypatch):
    mvi = _make_version_info()
    fake = tmp_path / "pyproject.toml"
    fake.write_text('[project]\nname = "serpentine3d"\nversion = "9.8.7"\n')
    monkeypatch.setattr(mvi, "PYPROJECT", fake)
    monkeypatch.setattr(mvi, "OUTPUT", tmp_path / "file_version_info.txt")
    assert mvi.project_version() == "9.8.7"
    text = mvi.main().read_text(encoding="utf-8")
    assert "StringStruct('ProductVersion', '9.8.7')" in text
    assert "filevers=(9, 8, 7, 0)" in text


def test_the_real_pyproject_version_is_the_one_used():
    import tomllib
    with open(ROOT / "pyproject.toml", "rb") as fh:
        declared = tomllib.load(fh)["project"]["version"]
    assert _make_version_info().project_version() == declared


def test_the_installer_takes_its_version_from_the_exe_it_packs():
    """pyproject -> serp3d.exe's resource -> the installer: one number."""
    iss = ISS.read_text()
    assert not re.search(r'#define AppVersion "', iss), "no hand-written version"
    assert re.search(
        r'#define AppVersion GetFileProductVersionString\(AppExe\)', iss)
    assert re.search(r'#define AppExe .*"dist\\serp3d\\serp3d\.exe"', iss)
    assert '#if AppVersion == ""' in iss and "#error" in iss


def test_the_installer_carries_version_information():
    iss = ISS.read_text()
    for line in ("VersionInfoVersion={#AppVersion}",
                 "VersionInfoTextVersion={#AppVersion}",
                 "VersionInfoProductName={#AppName}",
                 "VersionInfoProductVersion={#AppVersion}",
                 "VersionInfoProductTextVersion={#AppVersion}",
                 "VersionInfoCompany={#AppPublisher}",
                 "AppPublisher={#AppPublisher}"):
        assert line in iss, f"installer.iss is missing {line}"


def test_the_installer_shows_the_privacy_notice():
    """Software that sends anything to a system the user did not choose must
    show its privacy policy during installation."""
    iss = ISS.read_text()
    match = re.search(r"^InfoBeforeFile=(.+)$", iss, re.M)
    assert match, "installer.iss shows no privacy notice"
    notice = (WINDOWS / match.group(1).strip()).read_text(encoding="utf-8")
    assert "api.github.com" in notice
    assert "Check GitHub for updates on startup" in notice
    assert "code-signing-policy" in notice


# -- the published policy ---------------------------------------------------

def test_the_policy_carries_the_foundation_wording():
    text = POLICY.read_text(encoding="utf-8")
    assert text.startswith("# Code signing policy")
    assert REQUIRED_LINE in text
    assert "Committers and reviewers" in text
    assert re.search(r"Approvers.*Chisomo Banzi", text)
    assert "## Privacy" in text


def test_the_policy_names_every_service_the_app_can_reach():
    text = POLICY.read_text(encoding="utf-8")
    for host in ("api.github.com", "api.anthropic.com", "api.openai.com"):
        assert host in text
    assert "Codex" in text
    assert "screenshot" in text.lower()
    assert ".config/serpentine3d" in text


def test_the_policy_is_published_and_linked():
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    exclude = mkdocs.split("exclude_docs:", 1)[1].split("\n\n", 1)[0]
    assert "code-signing-policy.md" not in exclude
    assert "Code signing policy: code-signing-policy.md" in mkdocs
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "[Code signing policy](docs/code-signing-policy.md)" in readme
    site = (ROOT / "website" / "index.html").read_text(encoding="utf-8")
    assert 'href="docs/code-signing-policy/">Code signing policy' in site
    install = (ROOT / "docs" / "getstarted" / "install.md").read_text(encoding="utf-8")
    assert "[Code signing policy](../code-signing-policy.md)" in install
