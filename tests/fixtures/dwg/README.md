# DWG import fixture

`line-and-circle.dwgadd` is original test data authored for Serpentine3D and
distributed under the repository's MIT license. It contains only two model-space
entities, in millimetres:

- LINE from `(10, 20, 0)` to `(30, 20, 0)`.
- CIRCLE centred at `(45, 35, 0)`, radius `5`.

The source describes that geometry directly:

```text
HEADER.INSUNITS = 4
line (10 20 0) (30 20 0)
circle (45 35 0) 5
```

`line-and-circle.dwg` is the genuine binary R2000 DWG conversion of that source,
created using GNU LibreDWG 0.14's `examples/dwgadd` (default R2000 output):

```sh
dwgadd -o line-and-circle.dwg line-and-circle.dwgadd
```

It is not a renamed DXF and does not
contain third-party drawing content. The converter source archive is available
from https://ftp.gnu.org/gnu/libredwg/libredwg-0.14.tar.xz (SHA-256
`62ebb73b984f865960f20ed26619ea5f8789d5e3fd088fa40a2598384da81275`).

The tests consume the checked-in DWG directly, without generating it or
installing a converter at test time. Keeping the authored source alongside it
makes the expected analytic geometry independently inspectable. The binary was
also verified by converting back with `dwg2dxf` and inspecting both entities with
ezdxf.
