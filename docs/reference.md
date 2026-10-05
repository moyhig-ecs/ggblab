# Reference

## The applet

```{eval-rst}
.. autoclass:: ggblab.GeoGebra
   :members: command, new_construction, delete, set_xml, xml, value, kind, png, svg, listen, unlisten, events, errors, wait_update, mount

.. autofunction:: ggblab.find_server
```

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
