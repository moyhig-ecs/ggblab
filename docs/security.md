# Security considerations

This page lists the trust boundaries of version 2, what ggblab does not evaluate, the checks on the holder page, and
what remains open. The report channel and supported versions are in `SECURITY.md` at the root of the repository.

## Trust boundaries

| Party | Trusted for | Not trusted for |
| ----- | ----------- | --------------- |
| The notebook's user (the kernel) | everything: it runs code by design | — |
| The relay's handlers (`ggblab/...` on the Jupyter server) | serving the boxes of the logged-in user | telling apart two users or two documents on one server (see below) |
| A holder page (`ggblab/holder?mount=…`) | holding the applet of the box it names | its query string: `token` and `deploy` are checked, `params` is passed to the applet |
| A `.ggb` file, a construction XML, a DataFrame's `Value` column brought in from elsewhere | data | code: no string from them is run as Python |
| The Julia host | the same as the Python host: it builds the same page and talks to the same relay | — |

## What is not evaluated

A string read from a document (a value string, an `<input>` argument, a `Value` cell) is read in this order:

1. a literal number;
2. else a SymPy parse restricted to an allow-list of SymPy names, with no Python builtins, after refusing `__`, quotes,
   `[ ]`, `;`, backticks, backslashes and a `.` that is not a decimal point (`expr_from_value`);
3. else `None`.

There is no fallback to SymPy's `parse_expr` or `sympify` with their default globals. If `expr_from_value` cannot be
imported, the per-module parsers (`line`, `circle`, `curve`, `surface`, `plane`) raise `ImportError` instead of parsing.

## The holder page

- `token`: echoed into the page config only when the page was opened with `?token=`, and only if it consists of
  letters, digits, `-` and `_`; otherwise the request is answered with 400.
- `deploy`: accepted only under `https://www.geogebra.org/` or as a path on the same origin (starting with `/` and not
  followed by `/` or `\`); otherwise 400. The default is `https://www.geogebra.org/apps/deployggb.js`.
- Both configs written into the page (the applet's and the page's) escape `</` as `<\/`, so a value cannot end the
  script it is in. The Julia host's `mount` applies the same escape.

## What remains open

- **Box ownership.** The relay identifies a box by its key (`mount`) and does not check the caller against an owner.
  On a single-user server this is the server's own login boundary; on a server shared by several users it is not a
  boundary. How to close it is undecided; until then, run ggblab on single-user servers only.
- **The handling of document strings is provisional.** The order above (literal, restricted parse, `None`) and the
  removal of `point_from_value`'s fallback are in place; their final form may change in a later release.
- The applet script itself is loaded from GeoGebra's host without a subresource-integrity hash, and `params` reach the
  applet unchecked.
