"""Launch the ProxyKernel via IPKernelApp entrypoint."""
from ipykernel.kernelapp import IPKernelApp
from . import ProxyKernel


def main():
    IPKernelApp.launch_instance(kernel_class=ProxyKernel)


if __name__ == "__main__":
    main()
