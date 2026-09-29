# The eight verbs

The interface between a kernel and the applet is a closed set of eight verbs. Each verb is one call of the
[GeoGebra Apps API](https://geogebra.github.io/docs/reference/en/GeoGebra_Apps_API/). A request of any other kind is
answered with an error.

| Verb | Python | Julia | Apps API call | Reply |
|---|---|---|---|---|
| `eval` | `g.command(*commands)` | `command(g, commands...)` | `evalCommandGetLabels` | one entry per command |
| `new` | `g.new_construction()` | `new_construction(g)` | `newConstruction` | `True` |
| `delete` | `g.delete(label)` | `delete(g, label)` | `deleteObject` | `True` |
| `xml_in` | `g.set_xml(xml)` | `set_xml(g, xml)` | `setXML` | `True` |
| `xml_out` | `g.xml()` | `xml(g)` | `getXML` | the document |
| `value` | `g.value(label)` | `value(g, label)` | `getValue` | a number |
| `kind` | `g.kind(label)` | `kind(g, label)` | `getObjectType` | the runtime type |
| `listen` | `g.listen(callback, label=None)` | `listen(g, callback; label=nothing)` | listeners registered when the applet is mounted | — |

Calls are synchronous. Every call takes `timeout` (seconds, default 10).

## Reply of `command`

Each entry is one of three things:

- the labels GeoGebra returned for that command;
- `None`, when GeoGebra refused the command (a redefinition, or an error shown in the applet): see `g.errors()`;
- `{"error": …}`, when the Apps API threw for that command. The rest of the batch still runs.

## `set_xml` and the layout of the applet

A GeoGebra document carries, in its `<gui>` element, the layout it was saved with: which views are open, the input bar.
`set_xml(xml)` leaves that element out, so the applet keeps its own layout. `set_xml(xml, gui=True)` sends the document
as it is; a file saved with the algebra view closed then closes the side panel, and sending XML again does not reopen it.

The construction, the graphics view (`<euclidianView>`: coordinate system, axes) and the kernel settings are always sent.

## Events and errors

| Call | What it returns |
|---|---|
| `g.events(wait=0.0)` | what happened in the applet since the last call: objects added, updated |
| `g.errors(wait=0.0)` | the errors GeoGebra showed in the applet since the last call |
| `g.wait_update(label, timeout=30.0)` | the next update of one object, or `None` after the timeout |
| `g.listen(callback, label=None)` | registers a callback; it is called from `events()` |
| `g.unlisten(callback=None)` | removes one callback, or all |

## One applet per notebook

The applet belongs to the notebook, not to the Python object. Displaying `g` a second time in the same notebook shows a
pointer to the applet that is already mounted. Running the cell that mounts the applet again replaces the applet.
A notebook open in two browser tabs has one applet that serves requests; the other tab waits and takes over when the
first one is closed.

## Not among the verbs

Showing or hiding a layer (`setLayerVisible`), reading the applet state as a file (`getBase64`) and changing the
layout (`setPerspective`) are not part of the interface. `.ggb` files are read, not written.
