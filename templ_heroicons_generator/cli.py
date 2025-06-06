# templ_heroicons_generator/cli.py

import argparse
import sys
import os
import requests
import traceback

from .core import scanner
from .core import downloader
from .core import templ_builder
from .core import config


def parse_args() -> argparse.Namespace:
    """
    Parses command-line arguments for the Heroicons Templ generator.

    Defines and parses all available command-line options, providing default
    values from the `core.config` module where appropriate.

    Returns:
        An argparse.Namespace object containing the parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(
        description="Generate a heroicons.templ file from used icons, optimized for production.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        default=".",
        help="Root directory of the project containing .templ or .go (excluding _templ.go) files to scan.",  # MODIFIED HELP TEXT
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=config.DEFAULT_OUTPUT_DIR,
        help=(
            f"Output directory for '{config.OUTPUT_FILENAME}'. The Go package name is derived "
            "from this directory's base name."
        ),
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite the output file if it exists, even if content is identical.",
    )
    parser.add_argument(
        "--exclude-output",
        type=lambda x: str(x).lower() not in ["false", "0", "no"],
        default=True,
        help=(
            "Exclude source files (.templ, .go excluding _templ.go) within the --output-dir from scanning. "  # MODIFIED HELP TEXT
            "Use '--exclude-output false' to disable exclusion."
        ),
    )

    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed verbose output, including crawled files, during scanning and downloading.",
    )
    verbosity_group.add_argument(
        "--silent",
        "-s",
        action="store_true",
        help="Suppress all informational output. Only errors will be printed. Overrides --verbose.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview the generated output without writing to disk.",
    )
    parser.add_argument(
        "--default-class",
        default=config.DEFAULT_SVG_CLASS,
        help="Default CSS class attribute value for SVG elements.",
    )
    parser.add_argument(
        "--cache-dir",
        default=config.DEFAULT_CACHE_DIR,
        help="Directory to store cached SVG files and the icon list.",
    )
    args = parser.parse_args()

    if args.silent:
        args.verbose = False

    return args


def main():
    """
    Main function for the Command Line Interface.

    Orchestrates the Heroicons Templ component generation process:
    1. Parses arguments.
    2. Fetches (or loads from cache) the list of available Heroicons.
    3. Scans project files for icon usage.
    4. Downloads and caches SVGs for used icons.
    5. Generates the .templ Go package file.
    Includes top-level error handling and program exit codes.
    """
    args = parse_args()
    exit_code = 0

    try:
        if args.verbose:
            print("Verbose mode enabled.")

        valid_icons_list = downloader.fetch_heroicons_list(
            cache_dir=args.cache_dir, verbose=args.verbose, silent=args.silent
        )

        if (
            not valid_icons_list and args.verbose
        ):  # valid_icons_list can be an empty dict
            print(
                "  Warning: Could not fetch or parse the list of available icons (and no valid cache). "
                "Validation against the official list will be skipped.",
                file=sys.stderr,
            )

        if args.verbose:
            print("Scanning project for icon usage...")
        icons_to_generate = scanner.find_used_icons(
            input_dir=args.input_dir,
            output_dir_to_exclude=args.output_dir,
            exclude_output_dir_files=args.exclude_output,
            verbose=args.verbose,
            silent=args.silent,
            valid_icons_list=valid_icons_list,
        )

        if not icons_to_generate and not args.dry_run and not args.silent:
            print(
                "No icons found in project files matching the required format, or none were valid."
            )

        if args.verbose and icons_to_generate:
            print(
                f"Preparing to download/cache SVGs for {len(icons_to_generate)} icon(s)..."
            )
        elif args.verbose and not icons_to_generate:
            print("No icons to download/cache.")

        valid_icons_data, download_errors = downloader.download_svgs(
            icons_to_process=icons_to_generate,
            verbose=args.verbose,
            silent=args.silent,
            cache_dir=args.cache_dir,
        )

        if download_errors > 0:
            print(
                f"\nWarning: Encountered {download_errors} error(s) during SVG download/processing.",
                file=sys.stderr,
            )
            if not valid_icons_data and icons_to_generate and not args.dry_run:
                print(
                    "  Error: Failed to process any identified icons. Cannot generate package.",
                    file=sys.stderr,
                )
                exit_code = 1
            elif (
                icons_to_generate and args.verbose
            ):  # Check icons_to_generate before printing
                print(
                    f"  Proceeding with {len(valid_icons_data)} successfully processed icon(s).",
                    file=sys.stderr,
                )

        if exit_code == 0:  # Check exit_code before proceeding
            # Only proceed if there are icons to generate or if it's a dry run (to show empty output)
            # Or if user wants to generate an empty file if no icons were found (current behaviour)
            # For now, let's keep the behaviour of generating an empty file if no icons are found,
            # unless download_svgs failed catastrophically.
            if (
                args.verbose and not valid_icons_data and icons_to_generate
            ):  # Log if we identified icons but failed to get data
                print(
                    "  Note: No valid icon data to generate package from, though icons were identified."
                )
            elif args.verbose and not icons_to_generate:
                print("  No icons identified to generate the package from.")

            if args.verbose:  # General message, even if valid_icons_data is empty
                print("Generating Templ package...")

            generated_content = templ_builder.generate_heroicons_package(
                output_dir=args.output_dir,
                icons=valid_icons_data,  # Pass valid_icons_data which might be empty
                force=args.force,
                verbose=args.verbose,
                silent=args.silent,
                dry_run=args.dry_run,
                default_class=args.default_class,
            )

            if args.dry_run:
                if generated_content:
                    target_path = os.path.join(args.output_dir, config.OUTPUT_FILENAME)
                    try:
                        rel_target_path = os.path.relpath(target_path)
                    except ValueError:
                        rel_target_path = target_path
                    print(
                        f"\n--- Dry Run: Content that would be written to {rel_target_path} ---"
                    )
                    print(generated_content.strip())
                    print("--- End Dry Run ---")
                else:  # This case should ideally not happen if generate_heroicons_package always returns string on dry_run
                    print(
                        "\n--- Dry Run: No content was generated (or an issue occurred). ---"
                    )
        else:
            print(
                "Skipping package generation due to previous errors.", file=sys.stderr
            )

    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        exit_code = 130
    except requests.exceptions.RequestException as e:
        print(
            f"\nNetwork Error: A critical network error occurred: {e}", file=sys.stderr
        )
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        exit_code = 1
    except FileNotFoundError as e:
        print(f"\nFile System Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        exit_code = 1
    except OSError as e:
        print(f"\nOS Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        exit_code = 1
    except RuntimeError as e:
        print(f"\nRuntime Error: {e}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        exit_code = 1
    except Exception as e:
        print(f"\n--- Unexpected Error ---", file=sys.stderr)
        print(f"An unhandled error occurred: {e}", file=sys.stderr)
        print("\n--- Traceback ---", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("--- End Traceback ---", file=sys.stderr)
        exit_code = 1
    finally:
        if not args.silent:  # Ensure this is not printed if silent is true
            if exit_code == 0:
                print("Script finished successfully.")
            else:
                print(f"Script finished with errors (exit code {exit_code}).")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
