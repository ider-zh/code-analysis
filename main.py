import logging.config
from src.linux_kernel_v2.logic import (
    git_histroy_review,
    test_link_linux_kernel,
    linux_kernel_commit_history_load
)
import click
logging.config.fileConfig('config/logging.conf')


@click.group()
def cli():
    pass
        
@cli.command()
@click.option('--project_source_path', default="/mnt/wd01/github/linux_old1", help='project_source_path')
def linux_kernel_history_review(project_source_path):
    logging.info('start linux_kernel_history_review')
    linux_kernel_commit_history_load(project_source_path)
        
@cli.command()
@click.option('--project_source_path', default="/mnt/wd01/github/linux_old1", help='project_source_path')
@click.option('--version', default="v4", help='version')
def linux_kernel_history_links(project_source_path,version):
    logging.info('start linux_kernel_history_links')
    git_histroy_review(project_source_path, version)
    
    
@cli.command()
@click.option('--project_source_path', default="/mnt/wd01/github/linux_old1", help='project_source_path')
def linux_kernel_test_link(project_source_path):
    logging.info('start linux_kernel_test_link')
    test_link_linux_kernel(project_source_path)


@cli.command()
def test():
    pass
    
if __name__ == '__main__':
    cli()
    
