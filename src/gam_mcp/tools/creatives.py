"""Creative tools for Google Ad Manager."""

import base64
import logging
import re
from pathlib import Path
from typing import Any, List, Optional

from ..client import get_gam_client
from ..utils import safe_get, zeep_to_dict

logger = logging.getLogger(__name__)


def extract_size_from_filename(filename: str) -> tuple[Optional[int], Optional[int]]:
    """Extract size (e.g., '300x250') from filename.

    Args:
        filename: The filename to parse

    Returns:
        Tuple of (width, height) or (None, None) if not found
    """
    match = re.search(r'(\d+)x(\d+)', filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def upload_creative(
    file_path: str,
    advertiser_id: int,
    click_through_url: str,
    creative_name: Optional[str] = None,
    override_size_width: Optional[int] = None,
    override_size_height: Optional[int] = None,
    network_code: Optional[str] = None
) -> dict:
    """Upload an image creative to Ad Manager.

    Args:
        file_path: Path to the image file
        advertiser_id: ID of the advertiser
        click_through_url: Destination URL when creative is clicked
        creative_name: Optional name for the creative (defaults to auto-generated)
        override_size_width: Optional width to override the creative size (for serving into different slot)
        override_size_height: Optional height to override the creative size (for serving into different slot)
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with created creative details
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    path = Path(file_path)
    filename = path.name

    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    # Read and encode image
    with open(path, 'rb') as f:
        image_data = f.read()

    image_data_base64 = base64.b64encode(image_data).decode('utf-8')

    # Extract size from filename
    width, height = extract_size_from_filename(filename)

    if not width or not height:
        return {"error": f"Could not extract size from filename: {filename}. Expected format like '300x250'"}

    # Determine creative size (use override if provided)
    creative_width = override_size_width if override_size_width else width
    creative_height = override_size_height if override_size_height else height
    use_override = override_size_width is not None and override_size_height is not None

    # Generate name if not provided
    if creative_name is None:
        creative_name = f"Creative - {creative_width}x{creative_height} - {path.stem}"

    creative = {
        'xsi_type': 'ImageCreative',
        'name': creative_name,
        'advertiserId': advertiser_id,
        'destinationUrl': click_through_url,
        'size': {
            'width': creative_width,
            'height': creative_height,
            'isAspectRatio': False
        },
        'primaryImageAsset': {
            'assetByteArray': image_data_base64,
            'fileName': filename
        }
    }

    # Set overrideSize when using different dimensions than the actual image
    if use_override:
        creative['overrideSize'] = True

    created_creatives = creative_service.createCreatives([creative])

    if not created_creatives:
        return {"error": "Failed to create creative"}

    created = created_creatives[0]

    result = {
        "id": safe_get(created, 'id'),
        "name": safe_get(created, 'name'),
        "advertiser_id": advertiser_id,
        "size": f"{creative_width}x{creative_height}",
        "click_through_url": click_through_url,
        "message": f"Creative '{creative_name}' uploaded successfully"
    }

    if use_override:
        result["original_size"] = f"{width}x{height}"
        result["override_size"] = True

    return result


def upload_creative_from_base64(
    image_base64: str,
    filename: str,
    advertiser_id: int,
    click_through_url: str,
    width: int,
    height: int,
    creative_name: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Upload an image creative from base64 data.

    Args:
        image_base64: Base64 encoded image data
        filename: Original filename
        advertiser_id: ID of the advertiser
        click_through_url: Destination URL when creative is clicked
        width: Image width
        height: Image height
        creative_name: Optional name for the creative
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with created creative details
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    if creative_name is None:
        creative_name = f"Creative - {width}x{height}"

    creative = {
        'xsi_type': 'ImageCreative',
        'name': creative_name,
        'advertiserId': advertiser_id,
        'destinationUrl': click_through_url,
        'size': {
            'width': width,
            'height': height,
            'isAspectRatio': False
        },
        'primaryImageAsset': {
            'assetByteArray': image_base64,
            'fileName': filename
        }
    }

    created_creatives = creative_service.createCreatives([creative])

    if not created_creatives:
        return {"error": "Failed to create creative"}

    created = created_creatives[0]

    return {
        "id": created['id'],
        "name": created['name'],
        "advertiser_id": advertiser_id,
        "size": f"{width}x{height}",
        "message": "Creative uploaded successfully"
    }


def associate_creative_with_line_item(
    creative_id: int,
    line_item_id: int,
    size_override_width: Optional[int] = None,
    size_override_height: Optional[int] = None,
    network_code: Optional[str] = None
) -> dict:
    """Associate a creative with a line item.

    Args:
        creative_id: The creative ID
        line_item_id: The line item ID
        size_override_width: Optional width for size override
        size_override_height: Optional height for size override
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with association details
    """
    client = get_gam_client(network_code=network_code)
    lica_service = client.get_service('LineItemCreativeAssociationService')

    lica = {
        'creativeId': creative_id,
        'lineItemId': line_item_id,
    }

    if size_override_width and size_override_height:
        lica['sizes'] = [{
            'width': size_override_width,
            'height': size_override_height,
            'isAspectRatio': False
        }]

    created_licas = lica_service.createLineItemCreativeAssociations([lica])

    if not created_licas:
        return {"error": "Failed to create creative association"}

    return {
        "creative_id": creative_id,
        "line_item_id": line_item_id,
        "size_override": f"{size_override_width}x{size_override_height}" if size_override_width else None,
        "message": f"Creative {creative_id} associated with line item {line_item_id}"
    }


def upload_and_associate_creative(
    file_path: str,
    advertiser_id: int,
    line_item_id: int,
    click_through_url: str,
    creative_name: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Upload a creative and associate it with a line item in one operation.

    Args:
        file_path: Path to the image file
        advertiser_id: ID of the advertiser
        line_item_id: ID of the line item
        click_through_url: Destination URL
        creative_name: Optional name for the creative
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with both upload and association results
    """
    # First upload
    upload_result = upload_creative(
        file_path=file_path,
        advertiser_id=advertiser_id,
        click_through_url=click_through_url,
        creative_name=creative_name,
        network_code=network_code
    )

    if "error" in upload_result:
        return upload_result

    creative_id = upload_result["id"]

    # Then associate
    assoc_result = associate_creative_with_line_item(
        creative_id=creative_id,
        line_item_id=line_item_id,
        network_code=network_code
    )

    if "error" in assoc_result:
        return {
            "creative": upload_result,
            "association_error": assoc_result["error"]
        }

    return {
        "creative_id": creative_id,
        "creative_name": upload_result["name"],
        "size": upload_result["size"],
        "line_item_id": line_item_id,
        "click_through_url": click_through_url,
        "message": f"Creative uploaded and associated with line item {line_item_id}"
    }


def bulk_upload_creatives(
    folder_path: str,
    advertiser_id: int,
    line_item_id: int,
    click_through_url: str,
    name_prefix: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Upload all creatives from a folder and associate with a line item.

    Args:
        folder_path: Path to folder containing image files
        advertiser_id: ID of the advertiser
        line_item_id: ID of the line item
        click_through_url: Destination URL
        name_prefix: Optional prefix for creative names
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with upload results
    """
    folder = Path(folder_path)

    if not folder.exists():
        return {"error": f"Folder not found: {folder_path}"}

    # Find all image files
    extensions = ['*.jpg', '*.jpeg', '*.png', '*.gif', '*.JPG', '*.JPEG', '*.PNG', '*.GIF']
    files = []
    for ext in extensions:
        files.extend(folder.glob(ext))

    if not files:
        return {"error": f"No image files found in {folder_path}"}

    results = {
        "folder": folder_path,
        "line_item_id": line_item_id,
        "advertiser_id": advertiser_id,
        "uploaded": [],
        "failed": [],
        "total_files": len(files)
    }

    for file_path in sorted(files):
        creative_name = None
        if name_prefix:
            width, height = extract_size_from_filename(file_path.name)
            if width and height:
                creative_name = f"{name_prefix} - {width}x{height}"

        result = upload_and_associate_creative(
            file_path=str(file_path),
            advertiser_id=advertiser_id,
            line_item_id=line_item_id,
            click_through_url=click_through_url,
            creative_name=creative_name,
            network_code=network_code
        )

        if "error" in result:
            results["failed"].append({
                "file": file_path.name,
                "error": result["error"]
            })
        else:
            results["uploaded"].append({
                "file": file_path.name,
                "creative_id": result["creative_id"],
                "size": result["size"]
            })

    results["success_count"] = len(results["uploaded"])
    results["fail_count"] = len(results["failed"])
    results["message"] = f"Uploaded {results['success_count']} of {results['total_files']} creatives"

    return results


def get_creative(creative_id: int, network_code: Optional[str] = None) -> dict:
    """Get creative details by ID.

    Args:
        creative_id: The creative ID
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with creative details
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    statement = client.create_statement()
    statement = statement.Where("id = :id").WithBindVariable('id', creative_id)

    response = creative_service.getCreativesByStatement(statement.ToStatement())

    if 'results' not in response or len(response['results']) == 0:
        return {"error": f"Creative {creative_id} not found"}

    creative = response['results'][0]
    size = safe_get(creative, 'size')

    return {
        "id": safe_get(creative, 'id'),
        "name": safe_get(creative, 'name'),
        "advertiser_id": safe_get(creative, 'advertiserId'),
        "size": f"{safe_get(size, 'width')}x{safe_get(size, 'height')}" if size else None,
        "type": safe_get(creative, 'Creative.Type'),
        "destination_url": safe_get(creative, 'destinationUrl')
    }


def list_creatives_by_advertiser(
    advertiser_id: int,
    limit: int = 100,
    network_code: Optional[str] = None
) -> dict:
    """List creatives for an advertiser.

    Args:
        advertiser_id: The advertiser ID
        limit: Maximum number of creatives to return
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with creatives list
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    statement = client.create_statement()
    statement = statement.Where(
        "advertiserId = :advertiserId"
    ).WithBindVariable('advertiserId', advertiser_id).Limit(limit)

    response = creative_service.getCreativesByStatement(statement.ToStatement())

    if 'results' not in response:
        return {"creatives": [], "total": 0}

    creatives = []
    for c in response['results']:
        size = safe_get(c, 'size')
        creatives.append({
            "id": safe_get(c, 'id'),
            "name": safe_get(c, 'name'),
            "size": f"{safe_get(size, 'width')}x{safe_get(size, 'height')}" if size else None,
            "type": safe_get(c, 'Creative.Type')
        })

    return {
        "advertiser_id": advertiser_id,
        "creatives": creatives,
        "total": len(creatives)
    }


def update_creative(
    creative_id: int,
    destination_url: Optional[str] = None,
    name: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Update an existing creative's properties.

    Args:
        creative_id: The creative ID to update
        destination_url: New destination URL (click-through URL)
        name: New name for the creative
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with updated creative details
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    # First, get the existing creative
    statement = client.create_statement()
    statement = statement.Where("id = :id").WithBindVariable('id', creative_id)

    response = creative_service.getCreativesByStatement(statement.ToStatement())

    if 'results' not in response or len(response['results']) == 0:
        return {"error": f"Creative {creative_id} not found"}

    creative = response['results'][0]

    # Update the fields
    if destination_url is not None:
        creative['destinationUrl'] = destination_url

    if name is not None:
        creative['name'] = name

    # Update the creative
    updated_creatives = creative_service.updateCreatives([creative])

    if not updated_creatives:
        return {"error": "Failed to update creative"}

    updated = updated_creatives[0]
    size = safe_get(updated, 'size')

    return {
        "id": safe_get(updated, 'id'),
        "name": safe_get(updated, 'name'),
        "advertiser_id": safe_get(updated, 'advertiserId'),
        "size": f"{safe_get(size, 'width')}x{safe_get(size, 'height')}" if size else None,
        "type": safe_get(updated, 'Creative.Type'),
        "destination_url": safe_get(updated, 'destinationUrl'),
        "message": f"Creative {creative_id} updated successfully"
    }


def perform_creative_action(
    action: str,
    creative_id: Optional[int] = None,
    statement_query: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Perform an action on creatives.

    Args:
        action: Creative action, currently ActivateCreatives or DeactivateCreatives
        creative_id: Optional single creative ID
        statement_query: Optional full PQL statement query
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with update result
    """
    if action not in {"ActivateCreatives", "DeactivateCreatives"}:
        return {"error": "action must be ActivateCreatives or DeactivateCreatives"}
    if not creative_id and not statement_query:
        return {"error": "creative_id or statement_query is required"}

    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    if statement_query:
        statement = {"query": statement_query}
    else:
        statement = client.create_statement().Where(
            "id = :id"
        ).WithBindVariable("id", creative_id).ToStatement()

    result = creative_service.performCreativeAction(
        {"xsi_type": action},
        statement
    )

    return {
        "action": action,
        "creative_id": creative_id,
        "num_changes": safe_get(result, 'numChanges', 0),
        "message": f"{action} applied"
    }


def list_creative_templates(
    limit: int = 50,
    name_contains: Optional[str] = None,
    status: Optional[str] = "ACTIVE",
    template_type: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """List creative templates."""
    client = get_gam_client(network_code=network_code)
    template_service = client.get_service('CreativeTemplateService')

    conditions = []
    if status:
        conditions.append("status = :status")
    if template_type:
        conditions.append("type = :type")
    if name_contains:
        conditions.append("name LIKE :name")

    statement = client.create_statement()
    if conditions:
        statement = statement.Where(" AND ".join(conditions))
    if status:
        statement = statement.WithBindVariable("status", status)
    if template_type:
        statement = statement.WithBindVariable("type", template_type)
    if name_contains:
        statement = statement.WithBindVariable("name", f"%{name_contains}%")
    statement = statement.Limit(limit)

    response = template_service.getCreativeTemplatesByStatement(
        statement.ToStatement()
    )
    results = safe_get(response, 'results', []) or []

    return {
        "creative_templates": [
            _serialize_creative_template(template) for template in results
        ],
        "total": len(results),
        "limit": limit,
    }


def get_creative_template(
    creative_template_id: int,
    network_code: Optional[str] = None
) -> dict:
    """Get a creative template by ID."""
    client = get_gam_client(network_code=network_code)
    template_service = client.get_service('CreativeTemplateService')

    statement = client.create_statement()
    statement = statement.Where("id = :id").WithBindVariable(
        "id", creative_template_id
    )
    response = template_service.getCreativeTemplatesByStatement(
        statement.ToStatement()
    )
    results = safe_get(response, 'results', []) or []
    if not results:
        return {"error": f"Creative template {creative_template_id} not found"}

    return {"creative_template": _serialize_creative_template(results[0])}


def create_template_creative(
    advertiser_id: int,
    name: str,
    creative_template_id: int,
    width: int,
    height: int,
    variable_values: Any,
    destination_url: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Create a TemplateCreative from a creative template.

    variable_values may be either a mapping of uniqueName to value, or a list of
    GAM-ready creative template variable value dictionaries.
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    creative = {
        'xsi_type': 'TemplateCreative',
        'name': name,
        'advertiserId': advertiser_id,
        'size': {
            'width': width,
            'height': height,
            'isAspectRatio': False
        },
        'creativeTemplateId': creative_template_id,
        'creativeTemplateVariableValues': _build_template_variable_values(
            variable_values
        ),
    }
    if destination_url is not None:
        creative['destinationUrl'] = destination_url

    created_creatives = creative_service.createCreatives([creative])
    if not created_creatives:
        return {"error": "Failed to create template creative"}

    created = created_creatives[0]
    size = safe_get(created, 'size')
    return {
        "id": safe_get(created, 'id'),
        "name": safe_get(created, 'name'),
        "advertiser_id": advertiser_id,
        "creative_template_id": creative_template_id,
        "size": f"{safe_get(size, 'width', width)}x{safe_get(size, 'height', height)}",
        "type": "TemplateCreative",
        "message": f"Template creative '{name}' created successfully"
    }


def list_creative_wrappers(
    limit: int = 50,
    label_id: Optional[int] = None,
    status: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """List creative wrappers."""
    client = get_gam_client(network_code=network_code)
    wrapper_service = client.get_service('CreativeWrapperService')

    conditions = []
    if label_id is not None:
        conditions.append("labelId = :labelId")
    if status:
        conditions.append("status = :status")

    statement = client.create_statement()
    if conditions:
        statement = statement.Where(" AND ".join(conditions))
    if label_id is not None:
        statement = statement.WithBindVariable("labelId", label_id)
    if status:
        statement = statement.WithBindVariable("status", status)
    statement = statement.Limit(limit)

    response = wrapper_service.getCreativeWrappersByStatement(
        statement.ToStatement()
    )
    results = safe_get(response, 'results', []) or []
    return {
        "creative_wrappers": [
            _serialize_creative_wrapper(wrapper) for wrapper in results
        ],
        "total": len(results),
        "limit": limit,
    }


def create_html_creative_wrapper(
    label_id: int,
    html_header: Optional[str] = None,
    html_footer: Optional[str] = None,
    ordering: str = "NO_PREFERENCE",
    amp_head: Optional[str] = None,
    amp_body: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Create an HTML creative wrapper for a CREATIVE_WRAPPER label."""
    if not html_header and not html_footer:
        return {"error": "html_header or html_footer is required"}

    client = get_gam_client(network_code=network_code)
    wrapper_service = client.get_service('CreativeWrapperService')

    wrapper = {
        "labelId": label_id,
        "creativeWrapperType": "HTML",
        "ordering": ordering,
    }
    if html_header:
        wrapper["htmlHeader"] = html_header
    if html_footer:
        wrapper["htmlFooter"] = html_footer
    if amp_head:
        wrapper["ampHead"] = amp_head
    if amp_body:
        wrapper["ampBody"] = amp_body

    created_wrappers = wrapper_service.createCreativeWrappers([wrapper])
    if not created_wrappers:
        return {"error": "Failed to create creative wrapper"}

    created = created_wrappers[0]
    return {
        "creative_wrapper": _serialize_creative_wrapper(created),
        "message": f"Creative wrapper for label {label_id} created successfully"
    }


def perform_creative_wrapper_action(
    action: str,
    creative_wrapper_id: Optional[int] = None,
    statement_query: Optional[str] = None,
    network_code: Optional[str] = None
) -> dict:
    """Perform an action on creative wrappers."""
    if action not in {"ActivateCreativeWrappers", "DeactivateCreativeWrappers"}:
        return {
            "error": "action must be ActivateCreativeWrappers or DeactivateCreativeWrappers"
        }
    if not creative_wrapper_id and not statement_query:
        return {"error": "creative_wrapper_id or statement_query is required"}

    client = get_gam_client(network_code=network_code)
    wrapper_service = client.get_service('CreativeWrapperService')

    if statement_query:
        statement = {"query": statement_query}
    else:
        statement = client.create_statement().Where(
            "id = :id"
        ).WithBindVariable("id", creative_wrapper_id).ToStatement()

    result = wrapper_service.performCreativeWrapperAction(
        {"xsi_type": action},
        statement
    )
    return {
        "action": action,
        "creative_wrapper_id": creative_wrapper_id,
        "num_changes": safe_get(result, 'numChanges', 0),
        "message": f"{action} applied"
    }


def upload_html5_creative(
    file_path: str,
    advertiser_id: int,
    width: int,
    height: int,
    creative_name: Optional[str] = None,
    is_safe_frame_compatible: bool = True,
    network_code: Optional[str] = None
) -> dict:
    """Upload an HTML5 creative (ZIP bundle) to Ad Manager.

    Creates a GAM Html5Creative from a self-contained ZIP of HTML/JS/CSS assets.
    Suitable for in-app or web HTML5 placements; if the bundle is MRAID-compliant
    it can serve in environments that expect MRAID (e.g. via the Google Mobile
    Ads SDK) — that depends on the bundle contents, not on any flag set here.

    The click-through URL is NOT set on the creative — it must be embedded in
    the bundle itself via the clickTAG macro (e.g. ``var clickTag = "https://...";``
    in the bundle's HTML). GAM substitutes this at serve time. Unlike
    ImageCreative, Html5Creative has no ``destinationUrl`` field in the GAM API.

    Args:
        file_path: Path to the HTML5 ZIP bundle
        advertiser_id: ID of the advertiser
        width: Creative width in pixels
        height: Creative height in pixels
        creative_name: Optional name for the creative (defaults to auto-generated)
        is_safe_frame_compatible: Whether the creative works in SafeFrame (default: True)
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with created creative details
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    path = Path(file_path)
    filename = path.name

    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    if path.suffix.lower() != '.zip':
        return {"error": f"HTML5 creative must be a .zip bundle, got: {filename}"}

    with open(path, 'rb') as f:
        bundle_data = f.read()

    bundle_data_base64 = base64.b64encode(bundle_data).decode('utf-8')

    if creative_name is None:
        creative_name = f"HTML5 Creative - {width}x{height} - {path.stem}"

    creative = {
        'xsi_type': 'Html5Creative',
        'name': creative_name,
        'advertiserId': advertiser_id,
        'size': {
            'width': width,
            'height': height,
            'isAspectRatio': False
        },
        'html5Asset': {
            'assetByteArray': bundle_data_base64,
            'fileName': filename
        },
        'isSafeFrameCompatible': is_safe_frame_compatible
    }

    created_creatives = creative_service.createCreatives([creative])

    if not created_creatives:
        return {"error": "Failed to create HTML5 creative"}

    created = created_creatives[0]

    return {
        "id": safe_get(created, 'id'),
        "name": safe_get(created, 'name'),
        "advertiser_id": advertiser_id,
        "size": f"{width}x{height}",
        "type": "Html5Creative",
        "is_safe_frame_compatible": is_safe_frame_compatible,
        "message": f"HTML5 creative '{creative_name}' uploaded successfully"
    }


def upload_and_associate_html5_creative(
    file_path: str,
    advertiser_id: int,
    line_item_id: int,
    width: int,
    height: int,
    creative_name: Optional[str] = None,
    is_safe_frame_compatible: bool = True,
    network_code: Optional[str] = None
) -> dict:
    """Upload an HTML5 creative and associate it with a line item in one operation.

    The click-through URL is NOT a parameter here — for HTML5 bundles it must
    be embedded in the ZIP via the clickTAG macro (see upload_html5_creative).

    Args:
        file_path: Path to the HTML5 ZIP bundle
        advertiser_id: ID of the advertiser
        line_item_id: ID of the line item
        width: Creative width in pixels
        height: Creative height in pixels
        creative_name: Optional name for the creative
        is_safe_frame_compatible: Whether the creative works in SafeFrame (default: True)
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with both upload and association results
    """
    upload_result = upload_html5_creative(
        file_path=file_path,
        advertiser_id=advertiser_id,
        width=width,
        height=height,
        creative_name=creative_name,
        is_safe_frame_compatible=is_safe_frame_compatible,
        network_code=network_code
    )

    if "error" in upload_result:
        return upload_result

    creative_id = upload_result["id"]

    assoc_result = associate_creative_with_line_item(
        creative_id=creative_id,
        line_item_id=line_item_id,
        network_code=network_code
    )

    if "error" in assoc_result:
        return {
            "creative": upload_result,
            "association_error": assoc_result["error"]
        }

    return {
        "creative_id": creative_id,
        "creative_name": upload_result["name"],
        "advertiser_id": advertiser_id,
        "size": upload_result["size"],
        "type": "Html5Creative",
        "line_item_id": line_item_id,
        "message": f"HTML5 creative uploaded and associated with line item {line_item_id}"
    }


def create_third_party_creative(
    advertiser_id: int,
    name: str,
    width: int,
    height: int,
    snippet: str,
    expanded_snippet: Optional[str] = None,
    is_safe_frame_compatible: bool = True,
    network_code: Optional[str] = None
) -> dict:
    """Create a third-party creative (HTML/JavaScript ad tag).

    Use this for DCM/Campaign Manager tags, custom HTML ads, or any third-party
    ad server tags that need to be served through Google Ad Manager.

    Args:
        advertiser_id: ID of the advertiser
        name: Name for the creative
        width: Creative width in pixels
        height: Creative height in pixels
        snippet: The HTML/JavaScript code snippet (the ad tag)
        expanded_snippet: Optional expanded snippet for expandable creatives
        is_safe_frame_compatible: Whether the creative works in SafeFrame (default: True)
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with created creative details
    """
    client = get_gam_client(network_code=network_code)
    creative_service = client.get_service('CreativeService')

    creative = {
        'xsi_type': 'ThirdPartyCreative',
        'name': name,
        'advertiserId': advertiser_id,
        'size': {
            'width': width,
            'height': height,
            'isAspectRatio': False
        },
        'snippet': snippet,
        'isSafeFrameCompatible': is_safe_frame_compatible
    }

    if expanded_snippet:
        creative['expandedSnippet'] = expanded_snippet

    created_creatives = creative_service.createCreatives([creative])

    if not created_creatives:
        return {"error": "Failed to create third-party creative"}

    created = created_creatives[0]
    size = safe_get(created, 'size')

    return {
        "id": safe_get(created, 'id'),
        "name": safe_get(created, 'name'),
        "advertiser_id": advertiser_id,
        "size": f"{safe_get(size, 'width')}x{safe_get(size, 'height')}" if size else None,
        "type": "ThirdPartyCreative",
        "is_safe_frame_compatible": is_safe_frame_compatible,
        "message": f"Third-party creative '{name}' created successfully"
    }


def get_creative_preview_url(
    line_item_id: int,
    creative_id: int,
    site_url: str,
    network_code: Optional[str] = None
) -> dict:
    """Get a preview URL for a creative associated with a line item.

    This generates a preview URL that shows how the creative will appear
    on the specified site URL.

    Args:
        line_item_id: The line item ID
        creative_id: The creative ID
        site_url: The URL of the site where you want to preview the creative
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with preview URL
    """
    client = get_gam_client(network_code=network_code)
    lica_service = client.get_service('LineItemCreativeAssociationService')

    try:
        # Use positional arguments as the SOAP API expects them in order:
        # lineItemId, creativeId, siteUrl
        preview_url = lica_service.getPreviewUrl(
            line_item_id,
            creative_id,
            site_url
        )

        return {
            "line_item_id": line_item_id,
            "creative_id": creative_id,
            "site_url": site_url,
            "preview_url": preview_url,
            "message": "Preview URL generated successfully"
        }
    except Exception as e:
        return {
            "error": str(e),
            "line_item_id": line_item_id,
            "creative_id": creative_id,
            "site_url": site_url
        }


def list_creatives_by_line_item(
    line_item_id: int,
    limit: int = 100,
    network_code: Optional[str] = None
) -> dict:
    """List creatives associated with a line item.

    Args:
        line_item_id: The line item ID
        limit: Maximum number of creatives to return
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with creatives list and association details
    """
    client = get_gam_client(network_code=network_code)
    lica_service = client.get_service('LineItemCreativeAssociationService')
    creative_service = client.get_service('CreativeService')

    # Get line item creative associations
    statement = client.create_statement()
    statement = statement.Where(
        "lineItemId = :lineItemId"
    ).WithBindVariable('lineItemId', line_item_id).Limit(limit)

    response = lica_service.getLineItemCreativeAssociationsByStatement(
        statement.ToStatement()
    )

    if 'results' not in response or len(response['results']) == 0:
        return {
            "line_item_id": line_item_id,
            "creatives": [],
            "total": 0,
            "message": "No creatives associated with this line item"
        }

    # Get creative IDs from associations
    creative_ids = [safe_get(lica, 'creativeId') for lica in response['results']]
    associations_map = {
        safe_get(lica, 'creativeId'): {
            "status": safe_get(lica, 'status'),
            "sizes": safe_get(lica, 'sizes')
        }
        for lica in response['results']
    }

    # Fetch creative details
    creative_ids_str = ', '.join(str(cid) for cid in creative_ids if cid)
    creative_statement = client.create_statement()
    creative_statement = creative_statement.Where(f"id IN ({creative_ids_str})")

    creative_response = creative_service.getCreativesByStatement(
        creative_statement.ToStatement()
    )

    creatives = []
    if 'results' in creative_response:
        for c in creative_response['results']:
            cid = safe_get(c, 'id')
            size = safe_get(c, 'size')
            assoc = associations_map.get(cid, {})

            creatives.append({
                "id": cid,
                "name": safe_get(c, 'name'),
                "size": f"{safe_get(size, 'width')}x{safe_get(size, 'height')}" if size else None,
                "type": safe_get(c, 'Creative.Type'),
                "destination_url": safe_get(c, 'destinationUrl'),
                "association_status": assoc.get("status")
            })

    return {
        "line_item_id": line_item_id,
        "creatives": creatives,
        "total": len(creatives)
    }


def _build_template_variable_values(variable_values: Any) -> List[dict]:
    """Build GAM TemplateCreative variable values from simple input."""
    if isinstance(variable_values, list):
        return variable_values

    if not isinstance(variable_values, dict):
        raise ValueError("variable_values must be a dict or list")

    values = []
    for unique_name, value in variable_values.items():
        if isinstance(value, dict) and "xsi_type" in value:
            variable_value = dict(value)
            variable_value.setdefault("uniqueName", unique_name)
            values.append(variable_value)
            continue

        if isinstance(value, int):
            xsi_type = "LongCreativeTemplateVariableValue"
            soap_value = value
        elif isinstance(value, str) and value.startswith(("http://", "https://")):
            xsi_type = "UrlCreativeTemplateVariableValue"
            soap_value = value
        else:
            xsi_type = "StringCreativeTemplateVariableValue"
            soap_value = str(value)

        values.append({
            "xsi_type": xsi_type,
            "uniqueName": unique_name,
            "value": soap_value,
        })

    return values


def _serialize_creative_template(template: Any) -> dict:
    """Serialize a creative template SOAP object."""
    return {
        "id": safe_get(template, 'id'),
        "name": safe_get(template, 'name'),
        "description": safe_get(template, 'description'),
        "status": safe_get(template, 'status'),
        "type": safe_get(template, 'type'),
        "variables": zeep_to_dict(safe_get(template, 'variables', [])),
    }


def _serialize_creative_wrapper(wrapper: Any) -> dict:
    """Serialize a creative wrapper SOAP object."""
    return {
        "id": safe_get(wrapper, 'id'),
        "label_id": safe_get(wrapper, 'labelId'),
        "creative_wrapper_type": safe_get(wrapper, 'creativeWrapperType'),
        "status": safe_get(wrapper, 'status'),
        "ordering": safe_get(wrapper, 'ordering'),
        "html_header": safe_get(wrapper, 'htmlHeader'),
        "html_footer": safe_get(wrapper, 'htmlFooter'),
        "amp_head": safe_get(wrapper, 'ampHead'),
        "amp_body": safe_get(wrapper, 'ampBody'),
    }
