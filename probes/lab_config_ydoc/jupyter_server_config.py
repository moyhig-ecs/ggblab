# v2 test lab for the datalayer Jupyter MCP Server: JSD off, jupyter_server_ydoc (RTC) on, ggblab relay on, jupyter_server_mcp on
c = get_config()  # noqa
c.ServerApp.jpserver_extensions = {
    "jupyter_server_documents": False,
    "jupyter_server_ydoc": True,
    "jupyter_server_fileid": True,
    "ggblab.host.relay": True,
    "jupyter_server_mcp": True,
    "jupyterlab": True,
}
c.ServerApp.open_browser = False
c.ServerApp.disable_check_xsrf = False
