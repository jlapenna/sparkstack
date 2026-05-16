#!/usr/bin/env python3

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DASHBOARDS_DIR = Path("grafana/provisioning/dashboards")


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def find_panel(dashboard: dict, title: str):
    for panel in dashboard.get("panels", []):
        if panel.get("title") == title:
            return panel
        if "panels" in panel:
            for subpanel in panel["panels"]:
                if subpanel.get("title") == title:
                    return subpanel
    return None


def process_template(template_path: Path, output_path: Path):
    logger.info(f"Processing {template_path}...")
    template = load_json(template_path)
    dashboards_cache = {}

    new_panels = []
    panel_id_counter = 100

    for panel in template.get("panels", []):
        if "__TEMPLATE_REF__" in panel:
            ref = panel.pop("__TEMPLATE_REF__")

            # Ref can be a string or a dict
            if isinstance(ref, str):
                source_file, source_title = ref.split("|")
                extract_keys = None
            else:
                source_file, source_title = ref["source"].split("|")
                extract_keys = ref.get("extract")

            if source_file not in dashboards_cache:
                source_path = template_path.parent / source_file
                if not source_path.exists():
                    logger.error(f"Source dashboard not found: {source_path}")
                    new_panels.append(panel)
                    continue
                dashboards_cache[source_file] = load_json(source_path)

            source_panel = find_panel(dashboards_cache[source_file], source_title)
            if not source_panel:
                logger.error(f"Panel '{source_title}' not found in {source_file}")
                new_panels.append(panel)
                continue

            if extract_keys:
                # We are merging specific keys into the existing panel template
                compiled_panel = panel
                for key in extract_keys:
                    if key in source_panel:
                        compiled_panel[key] = json.loads(json.dumps(source_panel[key]))
                logger.info(
                    f"  -> Extracted {extract_keys} for '{compiled_panel.get('title')}' from {source_file}::'{source_title}'"
                )
            else:
                # Deep copy the whole panel
                compiled_panel = json.loads(json.dumps(source_panel))

                # Override specific fields from the template
                if "gridPos" in panel:
                    compiled_panel["gridPos"] = panel["gridPos"]

                # Optional overrides
                for k in ["title", "description", "transparent"]:
                    if k in panel:
                        compiled_panel[k] = panel[k]
                logger.info(f"  -> Injected '{source_title}' from {source_file}")

            # Ensure unique ID
            if "id" in compiled_panel:
                compiled_panel["id"] = panel_id_counter
                panel_id_counter += 1

            new_panels.append(compiled_panel)
        else:
            # Regular panel, just ensure unique ID
            if "id" in panel:
                panel["id"] = panel_id_counter
                panel_id_counter += 1
            new_panels.append(panel)

    template["panels"] = new_panels
    save_json(output_path, template)
    logger.info(f"Successfully built {output_path}")


def main():
    os.chdir(Path(__file__).parent)

    # Process all .template.json files
    for template_path in DASHBOARDS_DIR.glob("*.template.json"):
        output_path = template_path.with_name(template_path.name.replace(".template", ""))
        process_template(template_path, output_path)


if __name__ == "__main__":
    main()
