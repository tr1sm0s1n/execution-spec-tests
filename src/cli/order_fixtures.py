"""
Functions and CLI interface for recursively ordering and sorting .json files.

example: Usage

    ```
    order_fixtures -i input_dir -o output_dir
    ```


The CLI interface takes the paths of an input directory and an output
directory. It recursively processes each .json file in the input directory and
its subdirectories, and sorts lists and dictionaries alphabetically and
writes the sorted output to .json files to the corresponding locations in the
output directory.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, cast

import click


def recursive_sort(item: Dict[str, Any] | List[Any]) -> Dict[str, Any] | List[Any]:
    """
    Recursively sorts an item.

    If the item is a dictionary, it returns a new dictionary that is a sorted
    version of the input dictionary.
    If the item is a list, it returns a new list that is a sorted version of the
    input list. The elements of the list are also sorted if they are lists or
    dictionaries.

    Args:
        item: The item to be sorted. This can be a list or a dictionary.

    Returns:
        The sorted item.

    """
    if isinstance(item, dict):
        return dict(sorted((k, recursive_sort(v)) for k, v in item.items()))
    elif isinstance(item, list):
        try:
            return sorted(cast(List[Any], [recursive_sort(x) for x in item]))
        except TypeError:
            # If a TypeError is raised, we might be dealing with a list of dictionaries
            # Sort them based on their string representation
            return sorted((recursive_sort(x) for x in item), key=str)
    else:
        return item


def order_fixture(input_path: Path, output_path: Path) -> None:
    """
    Sorts a .json fixture.

    Reads a .json file from the input path, sorts the .json data and writes it
    to the output path.

    Args:
        input_path: The Path object of the input .json file.
        output_path: The Path object of the output .json file.

    Returns:
        None.

    """
    with input_path.open("r") as f:
        data = json.load(f)
    data = recursive_sort(data)
    with output_path.open("w") as f:
        json.dump(data, f, indent=4)


def process_directory(input_dir: Path, output_dir: Path):
    """
    Process a directory.

    Processes each .json file in the input directory and its subdirectories, and
    writes the sorted .json files to the corresponding locations in the output
    directory.

    Args:
        input_dir: The Path object of the input directory.
        output_dir: The Path object of the output directory.

    Returns:
        None.

    """
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
    for child in input_dir.iterdir():
        if child.is_dir():
            process_directory(child, output_dir / child.name)
        elif child.suffix == ".json":
            order_fixture(child, output_dir / child.name)


@click.command()
@click.option(
    "--input",
    "-i",
    "input_dir",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True),
    required=True,
    help="The input directory",
)
@click.option(
    "--output",
    "-o",
    "output_dir",
    type=click.Path(writable=True, file_okay=False, dir_okay=True),
    required=True,
    help="The output directory",
)
def order_fixtures(input_dir, output_dir):
    """Order json fixture by key recursively from the input directory."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    process_directory(input_dir, output_dir)


if __name__ == "__main__":
    order_fixtures()
