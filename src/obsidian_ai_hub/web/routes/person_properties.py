import logging
from fastapi import APIRouter, Depends, HTTPException, status

from obsidian_ai_hub.web import schemas, service
from obsidian_ai_hub.web.routes.deps import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Person Property Definitions Routes ---


@router.get(
    "/person-property-definitions",
    response_model=list[schemas.PersonPropertyDefinition],
)
def list_property_definitions(_=Depends(require_bearer_token)):
    return service.list_property_definitions()


@router.post(
    "/person-property-definitions",
    response_model=schemas.PersonPropertyDefinition,
    status_code=status.HTTP_201_CREATED,
)
def create_property_definition(
    body: schemas.PersonPropertyDefinitionCreateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.create_property_definition(
            key=body.key,
            display_name=body.display_name,
            data_type=body.data_type,
            cardinality=body.cardinality,
            source_type=body.source_type,
            aliases=body.aliases,
            options=[opt.model_dump() for opt in body.options],
        )
    except service.KeyConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "key_conflict"},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch(
    "/person-property-definitions/{property_definition_id}",
    response_model=schemas.PersonPropertyDefinition,
)
def update_property_definition(
    property_definition_id: str,
    body: schemas.PersonPropertyDefinitionUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_property_definition(
            property_definition_id,
            display_name=body.display_name,
            aliases=body.aliases,
            options=[opt.model_dump() for opt in body.options]
            if body.options is not None
            else None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.KeyConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "key_conflict"},
        ) from e
    except service.OptionInUseError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "option_in_use"},
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/person-property-definitions/{property_definition_id}",
    response_model=schemas.PersonPropertyDefinitionDeleteResponse,
)
def delete_property_definition(
    property_definition_id: str,
    _=Depends(require_bearer_token),
):
    try:
        return service.delete_property_definition(property_definition_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# --- Person Property Values Routes ---


@router.get(
    "/people/{person_id}/properties",
    response_model=list[schemas.PersonPropertyValue],
)
def list_person_properties(
    person_id: str,
    _=Depends(require_bearer_token),
):
    try:
        return service.list_person_properties(person_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post(
    "/people/{person_id}/properties",
    response_model=schemas.PersonPropertyValue,
    status_code=status.HTTP_201_CREATED,
)
def create_person_property_value(
    person_id: str,
    body: schemas.PersonPropertyValueCreateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.create_person_property_value(
            person_id=person_id,
            property_definition_id=body.property_definition_id,
            value=body.value,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
            note=body.note,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.VaultSourceReadOnlyError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Vault正本属性はWeb APIからの直接編集ができません。Vaultノートを編集して人物同期を行ってください。",
                "conflict_type": "vault_source_readonly",
            },
        ) from e
    except service.SingleCardinalityOverlapError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "single_cardinality_overlap"},
        ) from e
    except (ValueError, service.InvalidValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch(
    "/people/{person_id}/properties/{property_value_id}",
    response_model=schemas.PersonPropertyValue,
)
def update_person_property_value(
    person_id: str,
    property_value_id: str,
    body: schemas.PersonPropertyValueUpdateRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.update_person_property_value(
            property_value_id=property_value_id,
            value=body.value,
            valid_from=body.valid_from,
            valid_until=body.valid_until,
            note=body.note,
            provided=list(body.model_fields_set),
            expected_person_id=person_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.VaultSourceReadOnlyError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Vault正本属性はWeb APIからの直接編集ができません。Vaultノートを編集して人物同期を行ってください。",
                "conflict_type": "vault_source_readonly",
            },
        ) from e
    except service.SingleCardinalityOverlapError as e:
        raise HTTPException(
            status_code=409,
            detail={"message": str(e), "conflict_type": "single_cardinality_overlap"},
        ) from e
    except (ValueError, service.InvalidValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.put(
    "/people/{person_id}/properties/by-definition/{property_definition_id}",
    response_model=list[schemas.PersonPropertyValue],
)
def replace_person_property_values(
    person_id: str,
    property_definition_id: str,
    body: schemas.PersonPropertyBulkSaveRequest,
    _=Depends(require_bearer_token),
):
    try:
        return service.replace_person_property_values(
            person_id=person_id,
            property_definition_id=property_definition_id,
            items=[item.model_dump() for item in body.values],
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.VaultSourceReadOnlyError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Vault正本属性はWeb APIからの直接編集ができません。Vaultノートを編集して人物同期を行ってください。",
                "conflict_type": "vault_source_readonly",
            },
        ) from e
    except (ValueError, service.InvalidValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/people/{person_id}/properties/{property_value_id}",
    response_model=schemas.PersonPropertyValueDeleteResponse,
)
def delete_person_property_value(
    person_id: str,
    property_value_id: str,
    _=Depends(require_bearer_token),
):
    try:
        return service.delete_person_property_value(
            property_value_id, expected_person_id=person_id
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except service.VaultSourceReadOnlyError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Vault正本属性はWeb APIからの直接編集ができません。Vaultノートを編集して人物同期を行ってください。",
                "conflict_type": "vault_source_readonly",
            },
        ) from e
