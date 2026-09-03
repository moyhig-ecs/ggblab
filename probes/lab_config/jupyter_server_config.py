c.ServerApp.jpserver_extensions = {
    "ggblab.host.relay": True,
    "jupyter_server_documents": False,   # takes over the kernel websocket + processes outputs server-side (suspected to break comm_open)
}
