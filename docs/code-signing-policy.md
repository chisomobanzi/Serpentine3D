# Code signing policy

The Windows builds of Serpentine3D are digitally signed, so Windows can show you
who published the installer you are about to run.

Free code signing provided by [SignPath.io](https://about.signpath.io),
certificate by [SignPath Foundation](https://signpath.org).

## What gets signed

Only the Windows artefacts built by this project's own CI from this
repository's source:

- `serp3d.exe` — the application executable inside the bundle
- `Serpentine3D-Setup-x86_64.exe` — the Inno Setup installer

Every signed binary is produced by the
[Build Windows installer](https://github.com/chisomobanzi/Serpentine3D/blob/main/.github/workflows/build-windows.yml)
workflow from a tagged commit. Nothing is signed from a local machine, and no
third-party binary is submitted for signing on this subscription. Third-party
runtime libraries — Qt, OpenCASCADE, the Python runtime — are redistributed
inside the signed package as their publishers ship them.

The Linux AppImage and the macOS disk image are not covered by this policy.

## Team roles

Serpentine3D is currently maintained by one person, who therefore holds all
three roles. Any change to that will be reflected here.

| Role | Who | Responsibility |
|---|---|---|
| Authors | [Chisomo Banzi](https://github.com/chisomobanzi) | Commit directly to `main` |
| Reviewers | [Chisomo Banzi](https://github.com/chisomobanzi) | Review all contributions from outside the author list before merge |
| Approvers | [Chisomo Banzi](https://github.com/chisomobanzi) | Approve each individual signing request |

Multi-factor authentication is required on both the GitHub account and the
SignPath account. Every release requires a manual signing approval — signing is
never automatic on merge or on tag.

## Privacy

Serpentine3D does not transfer any information to other networked systems
except in the two cases below. It contains no telemetry, no analytics, no crash
reporting and no licence check, and it never transmits the models you make.

**Update check.** On launch, Serpentine3D asks the GitHub Releases API
(`api.github.com`) whether a newer version exists. The request sends nothing
about you or your work beyond what any HTTPS request necessarily reveals — your
IP address and the user agent `Serpentine3D-update-check`. GitHub's handling of
that request is covered by the
[GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-privacy-statement).

You can turn it off in three ways:

- **At install time on Windows** — clear the *Check GitHub for updates on
  startup* checkbox in the installer.
- **In the settings file** — set `check_updates` to `false` in
  `~/.config/serpentine3d/settings.json`
  (`%USERPROFILE%\.config\serpentine3d\settings.json` on Windows).
- **Per launch** — start the application with `SERP3D_NO_UPDATE_CHECK=1` set in
  the environment.

**AI assistant.** If — and only if — you supply your own Anthropic API key,
the optional AI assistant sends your prompts and the scene context you share
with it to the Anthropic Messages API (`api.anthropic.com`). The feature is
inert without a key, and no key ships with the application. This is governed by
[Anthropic's privacy policy](https://www.anthropic.com/legal/privacy).

Uninstalling Serpentine3D on Windows is done from **Settings ▸ Apps ▸ Installed
apps**, or via the uninstaller placed in the installation directory. It removes
everything the installer wrote. Your configuration and any models you saved are
left alone, since they are yours; delete `~/.serpentine3d` to remove those too.

## Reporting a problem

If you believe a signed Serpentine3D binary has been tampered with, or that this
policy is being violated, please
[open an issue](https://github.com/chisomobanzi/Serpentine3D/issues) — or, for
anything you would rather not discuss in public, write to SignPath Foundation at
`support@signpath.io` with your evidence.
