# Reference

## The applet

```{eval-rst}
.. autoclass:: ggblab.GeoGebra
   :members: command, new_construction, delete, set_xml, xml, value, kind, png, svg, listen, unlisten, events, errors, wait_update, mount, boxes

.. autoexception:: ggblab.host.html_host.NoHolderError

.. autofunction:: ggblab.find_server
```

### Timeouts, holders and the boxes list

Every call takes `timeout` (seconds). The request carries that timeout as its lifetime: if nobody holds the box for that long,
the request is dropped on the server and is never handed to a holder that turns up later. When the kernel stops waiting it also
withdraws the request (`POST ggblab/cancel`), so a command you gave up on does not run minutes afterwards.

A box is *held* by the page that polls it (a notebook output, a holder page, a headless browser). With `fail_fast=True` (the
default) a call on a box nobody holds raises `NoHolderError` — a `TimeoutError` — within `holder_grace` seconds (default 2.0)
instead of waiting out `timeout`; the message names the box and the holder URL. `GeoGebra(fail_fast=False)` restores the plain
wait. `g.boxes()` lists every box the server knows: `mount`, `holder` (is a live holder polling it), `queued`, `pending`,
`log_seq`, `xml_seq`.

Outside a kernel, name the server and the document: `GeoGebra(server_url="http://127.0.0.1:8888", token="...", doc="agent.ipynb")`.
Without a kernel the constructor refuses to guess a server (`ValueError`).

`g.events()` pulls the applet's events; when events fell off the box's log before they were pulled (the log keeps the last
4096), the gap is counted in `g.events_dropped`.

## Reading files and XML

`ggblab_extra` is installed with `pip install "ggblab[extra]"`.

```{eval-rst}
.. autofunction:: ggblab_extra.construction_io.read_ggb

.. autoclass:: ggblab_extra.construction_io.ConstructionIO
   :members:

.. autofunction:: ggblab.xml_errata.construction_xml

.. autofunction:: ggblab.xml_errata.without_gui
```

## The parser

```{eval-rst}
.. autofunction:: ggblab.parse.parse_cell

.. autofunction:: ggblab.parse.parse_statement

.. autoexception:: ggblab.parse.ParseError

.. autoexception:: ggblab.parse.UnknownHead

.. autoexception:: ggblab.parse.RelativeReference
```
