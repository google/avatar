import os
import pkg_resources

from grpc_tools import protoc
from invoke import task

package_directory = os.path.dirname(os.path.realpath(__file__))
os.environ["PATH"] = package_directory + ':' + os.environ["PATH"]


@task
def build_grpc(ctx):
    proto_include = pkg_resources.resource_filename('grpc_tools', '_proto')

    files = [f'pandora/{f}' for f in os.listdir(
        'proto/pandora') if f.endswith('.proto')]

    protoc.main([
        'grpc_tools.protoc',
        '-Iproto',
        f'-I{proto_include}',
        '--python_out=.',
        '--custom_grpc_out=.',
    ] + files)
