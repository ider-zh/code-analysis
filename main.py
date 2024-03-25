import logging.config
from src.linux_kernel_v2.logic import (
    git_histroy_review,
    cache_git_histroy_review,
    test_link_linux_kernel,
    linux_kernel_commit_history_load,
    repo_history_extract_cache,
    year_review,
    confuse_handle,
)
import click

logging.config.fileConfig("config/logging.conf")


@click.group()
def cli():
    pass


@cli.command()
@click.option(
    "--project_source_path",
    default="/mnt/wd01/github/linux_old1",
    help="project_source_path",
)
def linux_kernel_history_review(project_source_path):
    logging.info("start linux_kernel_history_review")
    linux_kernel_commit_history_load(project_source_path)


@cli.command()
@click.option(
    "--project_source_path",
    default="/mnt/wd01/github/linux_old1",
    help="project_source_path",
)
@click.option("--version", default="v7", help="version")
@click.option(
    "--usecache", default=False, help="是否从源代码中扫描代码，直接使用 cache"
)
def linux_kernel_history_links(project_source_path, version, usecache):
    if not usecache:
        logging.info("start linux_kernel_history_links")
        git_histroy_review(project_source_path, version)
    else:
        logging.info("start cache_git_histroy_review")
        cache_git_histroy_review(project_source_path, version)


@cli.command()
@click.option(
    "--project_source_path",
    default="/mnt/wd01/github/linux_old1",
    help="project_source_path",
)
@click.option("--version", default="v7", help="version")
@click.option("--year", default=2005, help="分析指定版本的kernel, 从 cache 中分析")
def linux_kernel_links_years(project_source_path, version, year):
    year_review(project_source_path, version, year)


@cli.command()
@click.option(
    "--project_source_path",
    default="/mnt/wd01/github/linux_old1",
    help="project_source_path",
)
@click.option("--version", default="v7", help="version")
def linux_kernel_history_extract_cache(project_source_path, version):
    repo_history_extract_cache(project_source_path, version)


@cli.command()
@click.option(
    "--project_source_path",
    default="/mnt/wd01/github/linux_old1",
    help="project_source_path",
)
def linux_kernel_test_link(project_source_path):
    logging.info("start linux_kernel_test_link")
    test_link_linux_kernel(project_source_path)


@cli.command()
@click.option("--version", default="v6", help="version")
def handle_confuse(version):
    confuse_handle(version)


@cli.command()
def test():
    pass


if __name__ == "__main__":
    cli()
