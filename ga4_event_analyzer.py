#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analizador de Eventos GA4 desde GTM y DataLayer (CLI & Streamlit UI)
Permite extraer las reglas de etiquetas GA4 de un contenedor GTM (.json)
y auditar un archivo JSON de eventos (exportación de DataLayer Auditor,
array directo de dataLayer pushes, o capturas de QA).
"""

import os
import re
import sys
import json
import argparse
from typing import Dict, List, Any, Tuple, Optional

DEFAULT_GTM_PATH = ""

REQUIRED_ITEM_FIELDS = [
    "item_id",
    "item_name",
    "price",
    "quantity",
    "currency",
]

WARNING_ITEM_FIELDS = {
    "price",
    "quantity",
    "currency",
}

# Parámetros opcionales aplicables ÚNICAMENTE a eventos personalizados (NO recomendados por Google).
# En los eventos recomendados por Google (login, sign_up, view_item_list, select_item, view_promotion,
# select_promotion, view_item, add_to_cart, remove_from_cart, view_cart, begin_checkout, add_shipping_info,
# add_payment_info, purchase, generate_lead), todos los parámetros de la etiqueta GTM son obligatorios.
OPTIONAL_PARAMS_BY_EVENT = {
    "web_error": {"items", "items_names"},
    "impression": {"items", "items_names"},
    "funnel_step": {"items", "items_names"},
    "services": {"items", "items_names"},
    "logout": {"method"},
    "begin_checkout": {"coupon"},
    "add_shipping_info": {"coupon", "shipping_tier"},
    "add_payment_info": {"coupon"},
    "purchase": {"coupon", "shipping", "tax"},
}


def is_param_optional_for_event(ev_name: str, param_name: str) -> bool:
    if param_name in ("coupon", "shipping_tier", "shipping", "tax"):
        return True
    return param_name in OPTIONAL_PARAMS_BY_EVENT.get(ev_name, set())

IGNORED_SYSTEM_EVENTS = {
    "gtm.js",
    "gtm.dom",
    "gtm.load",
    "gtm.click",
    "gtm.linkClick",
    "gtm.scrollDepth",
    "gtm.formSubmit",
    "gtm.historyChange",
    "gtm.timer",
    "OneTrustLoaded",
    "OneTrustGroupsUpdated",
    "OptanonLoaded",
    "trackOptanonEvent",
    "queue_processed",
    "unnamed_push",
    "data_object",
    "array_push",
}


def get_builtin_default_gtm_spec() -> Dict[str, Any]:
    """
    Devuelve la especificación del contenedor de referencia integrado por defecto.
    """
    def mk_param(name: str, dl_path: Optional[str], is_comp: bool, ev_name: str) -> Dict[str, Any]:
        return {
            "parameter": name,
            "gtm_value": "{{DL_GA4_Items_Names_Concats}}" if is_comp else f"{{{{DL_GA4_{dl_path}}}}}",
            "dl_path": dl_path,
            "is_computed": is_comp,
            "optional": is_param_optional_for_event(ev_name, name),
        }

    raw_defs = [
        ("services", "GA4 - Event - web_error o services", [("content_type", "eventModel.content_type", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("funnel_step", "GA4 - Event - web_error o services", [("content_type", "eventModel.content_type", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("web_error", "GA4 - Event - web_error o services", [("content_type", "eventModel.content_type", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("impression", "GA4 - Event - web_error o services", [("content_type", "eventModel.content_type", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("login", "GA4 - Event - login", [("method", "eventModel.method", False), ("crm_id", "eventModel.crm_id", False), ("content_type", "eventModel.content_type", False)], [{"name": "u_crm_id", "gtm_value": "{{DL_GA4_eventModel.crm_id}}", "dl_path": "eventModel.crm_id"}]),
        ("logout", "GA4 - Event - logout o sign_up", [("method", "eventModel.method", False), ("content_type", "eventModel.content_type", False)], []),
        ("sign_up", "GA4 - Event - logout o sign_up", [("method", "eventModel.method", False), ("content_type", "eventModel.content_type", False)], []),
        ("generate_lead", "GA4 - Event - generate_lead", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("content_type", "eventModel.content_type", False)], []),
        ("view_item_list", "GA4 - event - view_item_list o select_item", [("item_list_id", "eventModel.item_list_id", False), ("item_list_name", "eventModel.item_list_name", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("select_item", "GA4 - event - view_item_list o select_item", [("item_list_id", "eventModel.item_list_id", False), ("item_list_name", "eventModel.item_list_name", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("view_promotion", "GA4 - event - view_promotion o select_promotion", [("creative_name", "eventModel.creative_name", False), ("creative_slot", "eventModel.creative_slot", False), ("promotion_id", "eventModel.promotion_id", False), ("promotion_name", "eventModel.promotion_name", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("select_promotion", "GA4 - event - view_promotion o select_promotion", [("creative_name", "eventModel.creative_name", False), ("creative_slot", "eventModel.creative_slot", False), ("promotion_id", "eventModel.promotion_id", False), ("promotion_name", "eventModel.promotion_name", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("view_item", "GA4 - Event - view_item o add_to_cart", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("add_to_cart", "GA4 - Event - view_item o add_to_cart", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("remove_from_cart", "GA4 - Event - view_item o add_to_cart", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("view_cart", "GA4 - Event - view_item o add_to_cart", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("begin_checkout", "GA4 - Event - begin_checkout", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("coupon", "eventModel.coupon", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("add_shipping_info", "GA4 - Event - add_shipping_info", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("coupon", "eventModel.coupon", False), ("shipping_tier", "eventModel.shipping_tier", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("add_payment_info", "GA4 - Event - add_payment_info", [("currency", "eventModel.currency", False), ("value", "eventModel.value", False), ("coupon", "eventModel.coupon", False), ("payment_type", "eventModel.payment_type", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
        ("purchase", "GA4 - Event - purchase", [("currency", "eventModel.currency", False), ("transaction_id", "eventModel.transaction_id", False), ("value", "eventModel.value", False), ("coupon", "eventModel.coupon", False), ("shipping", "eventModel.shipping", False), ("tax", "eventModel.tax", False), ("items", "eventModel.items", False), ("items_names", None, True)], []),
    ]

    rules: Dict[str, Dict[str, Any]] = {}
    for ev_name, t_name, p_list, u_props in raw_defs:
        rules[ev_name] = {
            "event_name": ev_name,
            "tag_id": "",
            "tag_name": t_name,
            "parameters": [mk_param(pn, dlp, isc, ev_name) for pn, dlp, isc in p_list],
            "user_properties": u_props,
        }

    return {
        "container_name": "Contenedor de referencia",
        "public_id": "GTM-XXXXXXX",
        "export_time": "",
        "event_rules": rules,
        "tags_summary": [],
        "variables": {},
    }


def parse_gtm_container(gtm_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extrae las reglas de validación de eventos GA4 a partir del JSON exportado de GTM.
    Mapea cada evento (según sus triggers CUSTOM_EVENT) con su etiqueta GA4 (`gaawe`),
    sus parámetros esperados y las rutas en el dataLayer.
    """
    cv = gtm_data.get("containerVersion", gtm_data)
    container_info = cv.get("container", {})
    tags = cv.get("tag", [])
    triggers = {tr["triggerId"]: tr for tr in cv.get("trigger", []) if "triggerId" in tr}
    variables = {v["name"]: v for v in cv.get("variable", []) if "name" in v}

    # Resolver variables de capa de datos (type == 'v') y JS personalizado (type == 'jsm')
    var_resolution: Dict[str, Dict[str, Any]] = {}
    for var_name, var_obj in variables.items():
        v_type = var_obj.get("type")
        params = {p["key"]: p.get("value") for p in var_obj.get("parameter", []) if "key" in p}
        if v_type == "v":
            dl_path = params.get("name", "")
            var_resolution[var_name] = {
                "type": "datalayer",
                "dl_path": dl_path,
                "variable_name": var_name,
            }
        elif v_type == "jsm":
            js_code = params.get("javascript", "")
            # Detectar si depende de otra variable {{...}}
            deps = re.findall(r"\{\{([^}]+)\}\}", js_code)
            var_resolution[var_name] = {
                "type": "custom_js",
                "dependencies": deps,
                "javascript": js_code,
                "variable_name": var_name,
            }
        else:
            var_resolution[var_name] = {
                "type": v_type,
                "variable_name": var_name,
            }

    event_rules: Dict[str, Dict[str, Any]] = {}
    ga4_tags_summary: List[Dict[str, Any]] = []

    for tag in tags:
        if tag.get("type") != "gaawe":
            continue

        tag_name = tag.get("name", "Unnamed GA4 Tag")
        tag_id = tag.get("tagId", "")
        firing_trigger_ids = tag.get("firingTriggerId", [])

        # Extraer parámetros de eventSettingsTable y userProperties
        event_params: List[Dict[str, Any]] = []
        user_props: List[Dict[str, Any]] = []

        for p in tag.get("parameter", []):
            if p.get("key") == "eventSettingsTable":
                for item in p.get("list", []):
                    m = {x["key"]: x.get("value", "") for x in item.get("map", []) if "key" in x}
                    param_name = m.get("parameter", "")
                    param_val_ref = m.get("parameterValue", "")
                    var_match = re.match(r"^\{\{([^}]+)\}\}$", param_val_ref.strip())
                    resolved_var = var_resolution.get(var_match.group(1), {}) if var_match else {}

                    dl_path = resolved_var.get("dl_path")
                    is_computed = resolved_var.get("type") == "custom_js"
                    if not dl_path and not is_computed:
                        # Fallback por defecto a eventModel.<param_name>
                        dl_path = f"eventModel.{param_name}"

                    event_params.append({
                        "parameter": param_name,
                        "gtm_value": param_val_ref,
                        "dl_path": dl_path,
                        "is_computed": is_computed,
                        "dependencies": resolved_var.get("dependencies", []),
                    })

            elif p.get("key") == "userProperties":
                for item in p.get("list", []):
                    m = {x["key"]: x.get("value", "") for x in item.get("map", []) if "key" in x}
                    prop_name = m.get("name", "")
                    prop_val_ref = m.get("value", "")
                    var_match = re.match(r"^\{\{([^}]+)\}\}$", prop_val_ref.strip())
                    resolved_var = var_resolution.get(var_match.group(1), {}) if var_match else {}
                    user_props.append({
                        "name": prop_name,
                        "gtm_value": prop_val_ref,
                        "dl_path": resolved_var.get("dl_path", f"eventModel.{prop_name}"),
                    })

        # Identificar qué nombres de evento disparan este tag
        triggered_events: List[str] = []
        for tr_id in firing_trigger_ids:
            tr = triggers.get(tr_id, {})
            if tr.get("type") == "CUSTOM_EVENT":
                for f in tr.get("customEventFilter", []):
                    f_params = {x["key"]: x.get("value", "") for x in f.get("parameter", []) if "key" in x}
                    if f_params.get("arg0") == "{{_event}}" and f_params.get("arg1"):
                        triggered_events.append(f_params["arg1"])

        ga4_tags_summary.append({
            "tag_id": tag_id,
            "tag_name": tag_name,
            "events": triggered_events,
            "parameters": event_params,
            "user_properties": user_props,
        })

        for ev_name in triggered_events:
            tailored_params = [
                {**ep, "optional": is_param_optional_for_event(ev_name, ep["parameter"])}
                for ep in event_params
            ]
            event_rules[ev_name] = {
                "event_name": ev_name,
                "tag_id": tag_id,
                "tag_name": tag_name,
                "parameters": tailored_params,
                "user_properties": user_props,
            }

    return {
        "container_name": container_info.get("name", "Desconocido"),
        "public_id": container_info.get("publicId", "GTM-XXXX"),
        "export_time": gtm_data.get("exportTime", ""),
        "event_rules": event_rules,
        "tags_summary": ga4_tags_summary,
        "variables": var_resolution,
    }


def extract_events_from_input(raw_json: Any) -> List[Dict[str, Any]]:
    """
    Normaliza cualquier archivo JSON de eventos soportado a una lista uniforme de registros:
    Cada elemento devuelto tiene:
      - index: int (1-based)
      - timestamp: str
      - url: str
      - origin: str
      - payload: dict (el objeto empujado al dataLayer)
      - event_name: str
    Soporta:
      1. Exportación de la extensión DataLayer Auditor ({ "auditedEvents": [...], "dataLayerPushes": [...] })
      2. Array directo de objetos dataLayer ([ { "event": "...", "eventModel": {...} }, ... ])
      3. Diccionario con listas de eventos de scripts de QA (ej: { "events": [...] } o { "header_tel": [...], ... })
    """
    normalized: List[Dict[str, Any]] = []

    if isinstance(raw_json, dict):
        if "auditedEvents" in raw_json and isinstance(raw_json["auditedEvents"], list):
            for idx, item in enumerate(raw_json["auditedEvents"], start=1):
                payload = item.get("data") if isinstance(item, dict) and "data" in item else item
                if not isinstance(payload, dict):
                    continue
                ev_name = (
                    item.get("explicitEvent")
                    or payload.get("event")
                    or item.get("eventName")
                    or "unnamed_push"
                )
                normalized.append({
                    "index": idx,
                    "timestamp": item.get("timestamp", ""),
                    "url": item.get("url", ""),
                    "origin": item.get("origin", "dataLayer"),
                    "payload": payload,
                    "event_name": str(ev_name),
                })
            return normalized

        if "dataLayerPushes" in raw_json and isinstance(raw_json["dataLayerPushes"], list):
            for idx, payload in enumerate(raw_json["dataLayerPushes"], start=1):
                if not isinstance(payload, dict):
                    continue
                normalized.append({
                    "index": idx,
                    "timestamp": "",
                    "url": "",
                    "origin": "dataLayerPushes",
                    "payload": payload,
                    "event_name": str(payload.get("event", "unnamed_push")),
                })
            return normalized

        if "events" in raw_json and isinstance(raw_json["events"], list):
            for idx, payload in enumerate(raw_json["events"], start=1):
                if not isinstance(payload, dict):
                    continue
                normalized.append({
                    "index": idx,
                    "timestamp": "",
                    "url": "",
                    "origin": "events",
                    "payload": payload,
                    "event_name": str(payload.get("event", "unnamed_push")),
                })
            return normalized

        # Si es un único objeto evento directo {"event": "purchase", "eventModel": {...}}
        if "event" in raw_json or "eventModel" in raw_json:
            normalized.append({
                "index": 1,
                "timestamp": "",
                "url": "",
                "origin": "single_event",
                "payload": raw_json,
                "event_name": str(raw_json.get("event", "unnamed_push")),
            })
            return normalized

        # Diccionario de secciones de QA (ej. clicks_verification_clean.json o qa_home_eval.json)
        idx_counter = 1
        for key, val in raw_json.items():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        # Puede ser un contenedor con sub-lista "events" (ej. card_clicks_matrix.json)
                        if "events" in item and isinstance(item["events"], list) and "event" not in item:
                            for sub_ev in item["events"]:
                                if isinstance(sub_ev, dict):
                                    normalized.append({
                                        "index": idx_counter,
                                        "timestamp": "",
                                        "url": "",
                                        "origin": f"{key} ({item.get('element', '')})",
                                        "payload": sub_ev,
                                        "event_name": str(sub_ev.get("event", "unnamed_push")),
                                    })
                                    idx_counter += 1
                        else:
                            normalized.append({
                                "index": idx_counter,
                                "timestamp": "",
                                "url": "",
                                "origin": key,
                                "payload": item,
                                "event_name": str(item.get("event", "unnamed_push")),
                            })
                            idx_counter += 1
        return normalized

    elif isinstance(raw_json, list):
        idx_counter = 1
        for item in raw_json:
            if not isinstance(item, dict):
                continue
            # Si es formato de extensión directo [ { "data": {...}, "timestamp": "..." } ]
            if "data" in item and isinstance(item["data"], dict) and ("timestamp" in item or "eventName" in item):
                payload = item["data"]
                ev_name = (
                    item.get("explicitEvent")
                    or payload.get("event")
                    or item.get("eventName")
                    or "unnamed_push"
                )
                normalized.append({
                    "index": idx_counter,
                    "timestamp": item.get("timestamp", ""),
                    "url": item.get("url", ""),
                    "origin": item.get("origin", "dataLayer"),
                    "payload": payload,
                    "event_name": str(ev_name),
                })
                idx_counter += 1
            # Si es formato matriz de QA [ { "element": "...", "events": [...] } ]
            elif "events" in item and isinstance(item["events"], list) and "event" not in item:
                for sub_ev in item["events"]:
                    if isinstance(sub_ev, dict):
                        normalized.append({
                            "index": idx_counter,
                            "timestamp": "",
                            "url": "",
                            "origin": item.get("element", "qa_matrix"),
                            "payload": sub_ev,
                            "event_name": str(sub_ev.get("event", "unnamed_push")),
                        })
                        idx_counter += 1
            else:
                normalized.append({
                    "index": idx_counter,
                    "timestamp": "",
                    "url": "",
                    "origin": "direct_array",
                    "payload": item,
                    "event_name": str(item.get("event", "unnamed_push")),
                })
                idx_counter += 1

    return normalized


def get_nested_value(data: Dict[str, Any], path: str) -> Tuple[bool, Any]:
    """
    Obtiene un valor anidado por ruta con puntos (ej: 'eventModel.currency').
    Devuelve (existe_clave, valor).
    También comprueba si el parámetro se envió en la raíz o dentro de 'ecommerce' por error.
    """
    if not path:
        return False, None
    parts = path.split(".")
    curr: Any = data
    for p in parts:
        if isinstance(curr, dict) and p in curr:
            curr = curr[p]
        else:
            return False, None
    return True, curr


def is_empty_or_invalid_value(val: Any) -> Tuple[bool, str]:
    """
    Verifica si un valor es nulo, vacío o contiene strings inválidos como 'undefined', 'null', 'NaN'.
    Devuelve (es_invalido, motivo).
    """
    if val is None:
        return True, "Valor nulo (null/None)"
    if isinstance(val, str):
        stripped = val.strip()
        if stripped == "":
            return True, "Cadena vacía (\"\")"
        if stripped.lower() in ("undefined", "null", "nan"):
            return True, f"Valor literal inválido ('{stripped}')"
    if isinstance(val, list) and len(val) == 0:
        return True, "Array vacío ([])"
    if isinstance(val, dict) and len(val) == 0:
        return True, "Objeto vacío ({})"
    return False, ""


def validate_items_array(items: Any, event_name: str) -> List[Dict[str, str]]:
    """
    Valida la estructura del array 'items' de GA4 Ecommerce.
    Comprueba que sea una lista no vacía y que cada item tenga los campos requeridos y tipos válidos.
    """
    issues: List[Dict[str, str]] = []
    if not isinstance(items, list):
        issues.append({
            "severity": "error",
            "field": "eventModel.items",
            "message": f"'items' debe ser un array (lista), pero se recibió {type(items).__name__}.",
        })
        return issues

    if len(items) == 0:
        issues.append({
            "severity": "error",
            "field": "eventModel.items",
            "message": "El array 'items' está vacío ([]). Debe contener al menos 1 producto/servicio.",
        })
        return issues

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append({
                "severity": "error",
                "field": f"eventModel.items[{i}]",
                "message": f"El elemento items[{i}] no es un objeto válido.",
            })
            continue

        for req_field in REQUIRED_ITEM_FIELDS:
            is_warn_field = req_field in WARNING_ITEM_FIELDS
            if req_field not in item:
                issues.append({
                    "severity": "warning" if is_warn_field else "error",
                    "field": f"eventModel.items[{i}].{req_field}",
                    "message": f"Falta la propiedad '{req_field}' en items[{i}].",
                })
            else:
                val = item[req_field]
                inv, reason = is_empty_or_invalid_value(val)
                if inv:
                    issues.append({
                        "severity": "warning" if is_warn_field else "error",
                        "field": f"eventModel.items[{i}].{req_field}",
                        "message": f"Propiedad '{req_field}' en items[{i}] inválida: {reason}.",
                    })
                elif req_field == "price":
                    # Validar que sea numérico o convertible a número
                    if isinstance(val, str):
                        try:
                            float(val.replace(",", "."))
                            issues.append({
                                "severity": "warning",
                                "field": f"eventModel.items[{i}].price",
                                "message": f"'price' en items[{i}] se envía como string ('{val}') en lugar de número.",
                            })
                        except ValueError:
                            issues.append({
                                "severity": "warning",
                                "field": f"eventModel.items[{i}].price",
                                "message": f"'price' en items[{i}] no es un número válido ('{val}').",
                            })
    return issues


def audit_single_event(
    event_record: Dict[str, Any],
    gtm_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Evalúa un evento individual contra las reglas del contenedor GTM.
    """
    ev_name = event_record["event_name"]
    payload = event_record["payload"]
    event_rules = gtm_spec.get("event_rules", {})

    issues: List[Dict[str, str]] = []
    param_results: List[Dict[str, Any]] = []
    computed_values: Dict[str, Any] = {}

    if ev_name not in event_rules:
        is_system = ev_name in IGNORED_SYSTEM_EVENTS or ev_name.startswith("gtm.")
        return {
            "index": event_record["index"],
            "event_name": ev_name,
            "timestamp": event_record.get("timestamp", ""),
            "url": event_record.get("url", ""),
            "origin": event_record.get("origin", ""),
            "is_ga4_tracked": False,
            "is_system_event": is_system,
            "tag_name": None,
            "status": "IGNORED" if is_system else "UNTRACKED",
            "issues": [] if is_system else [{
                "severity": "info",
                "field": "event",
                "message": f"El evento '{ev_name}' no tiene ninguna etiqueta GA4 configurada en el contenedor GTM.",
            }],
            "param_results": [],
            "computed_values": {},
            "payload": payload,
        }

    rule = event_rules[ev_name]
    tag_name = rule["tag_name"]

    # Verificar si existe eventModel cuando la etiqueta lo requiere
    uses_event_model = any(
        (p.get("dl_path") or "").startswith("eventModel.")
        for p in rule["parameters"]
        if not p.get("is_computed")
    )
    if uses_event_model and "eventModel" not in payload:
        # Comprobar si se usó 'ecommerce' en lugar de 'eventModel'
        if "ecommerce" in payload:
            issues.append({
                "severity": "error",
                "field": "eventModel",
                "message": "No se encontró 'eventModel', pero existe 'ecommerce'. En este contenedor GTM las variables leen de 'eventModel.*'.",
            })
        else:
            issues.append({
                "severity": "error",
                "field": "eventModel",
                "message": "Falta el objeto raíz 'eventModel' requerido por las variables de GTM.",
            })

    # Evaluar cada parámetro esperado en la etiqueta
    for p in rule["parameters"]:
        p_name = p["parameter"]
        dl_path = p.get("dl_path")
        is_computed = p.get("is_computed", False)
        is_optional = is_param_optional_for_event(ev_name, p_name)

        if is_computed:
            # Simular cálculo de DL_GA4_Items_Names_Concats
            if "DL_GA4_Items_Names_Concats" in p.get("gtm_value", ""):
                exists_items, items_val = get_nested_value(payload, "eventModel.items")
                if exists_items and isinstance(items_val, list):
                    names = [
                        str(it["item_name"])
                        for it in items_val
                        if isinstance(it, dict) and it.get("item_name") is not None and str(it.get("item_name")).strip() != ""
                    ]
                    concat_str = " + ".join(names)
                    computed_values[p_name] = concat_str
                    if not concat_str:
                        issues.append({
                            "severity": "error",
                            "field": p_name,
                            "message": f"El parámetro calculado '{p_name}' ({{{{DL_GA4_Items_Names_Concats}}}}) resultará vacío porque ningún item tiene 'item_name'.",
                        })
                        param_results.append({
                            "parameter": p_name,
                            "dl_path": "Calculado de eventModel.items[*].item_name",
                            "status": "ERROR",
                            "value": "",
                            "note": "Resultado vacío",
                            "optional": is_optional,
                        })
                    else:
                        param_results.append({
                            "parameter": p_name,
                            "dl_path": "Calculado de eventModel.items[*].item_name",
                            "status": "OK",
                            "value": concat_str,
                            "note": "Calculado por variable JS en GTM",
                            "optional": is_optional,
                        })
                elif is_optional:
                    computed_values[p_name] = ""
                    param_results.append({
                        "parameter": p_name,
                        "dl_path": "Calculado de eventModel.items[*].item_name",
                        "status": "OPTIONAL_OMITTED",
                        "value": None,
                        "note": "Parámetro opcional omitido (no hay eventModel.items)",
                        "optional": True,
                    })
                else:
                    computed_values[p_name] = ""
                    issues.append({
                        "severity": "error",
                        "field": p_name,
                        "message": f"El parámetro '{p_name}' ({{{{DL_GA4_Items_Names_Concats}}}}) no puede calcularse porque falta 'eventModel.items'.",
                    })
                    param_results.append({
                        "parameter": p_name,
                        "dl_path": "Calculado de eventModel.items[*].item_name",
                        "status": "MISSING",
                        "value": None,
                        "note": "Falta eventModel.items",
                        "optional": False,
                    })
            continue

        # Parámetro directo de DataLayer
        exists, val = get_nested_value(payload, dl_path)
        if not exists:
            if is_optional:
                param_results.append({
                    "parameter": p_name,
                    "dl_path": dl_path,
                    "status": "OPTIONAL_OMITTED",
                    "value": None,
                    "note": "Parámetro opcional en este evento (no enviado)",
                    "optional": True,
                })
                continue

            # Comprobar si está en la raíz del payload o en ecommerce por error de implementación
            alt_key = dl_path.split(".")[-1]
            in_root = alt_key in payload
            in_ecomm = isinstance(payload.get("ecommerce"), dict) and alt_key in payload["ecommerce"]
            hint = ""
            if in_root:
                hint = f" (Se encontró '{alt_key}' en la raíz del evento, pero GTM lo busca en '{dl_path}')"
            elif in_ecomm:
                hint = f" (Se encontró '{alt_key}' dentro de 'ecommerce', pero GTM lo busca en '{dl_path}')"

            issues.append({
                "severity": "error",
                "field": dl_path,
                "message": f"Falta el parámetro '{p_name}' (esperado en '{dl_path}'){hint}.",
            })
            param_results.append({
                "parameter": p_name,
                "dl_path": dl_path,
                "status": "MISSING",
                "value": None,
                "note": f"No encontrado en {dl_path}{hint}",
                "optional": False,
            })
        else:
            is_inv, reason = is_empty_or_invalid_value(val)
            if is_inv:
                is_literal_undef = isinstance(val, str) and val.strip().lower() in ("undefined", "null", "nan")
                if is_optional and not is_literal_undef:
                    param_results.append({
                        "parameter": p_name,
                        "dl_path": dl_path,
                        "status": "OPTIONAL_OMITTED",
                        "value": val,
                        "note": f"Opcional sin valor ({reason})",
                        "optional": True,
                    })
                else:
                    issues.append({
                        "severity": "error",
                        "field": dl_path,
                        "message": f"El parámetro '{p_name}' ('{dl_path}') tiene un valor inválido: {reason}.",
                    })
                    param_results.append({
                        "parameter": p_name,
                        "dl_path": dl_path,
                        "status": "EMPTY/INVALID",
                        "value": val,
                        "note": reason,
                        "optional": is_optional,
                    })
            else:
                param_results.append({
                    "parameter": p_name,
                    "dl_path": dl_path,
                    "status": "OK",
                    "value": val,
                    "note": "OK",
                    "optional": is_optional,
                })

                # Si el parámetro es 'items', validar la estructura detallada de los items
                if p_name == "items":
                    item_issues = validate_items_array(val, ev_name)
                    issues.extend(item_issues)

    # Detectar parámetros extra en eventModel que NO están configurados en la etiqueta GTM
    expected_dl_paths = {
        p["dl_path"] for p in rule["parameters"] if not p.get("is_computed") and p.get("dl_path")
    }
    if isinstance(payload.get("eventModel"), dict):
        for k in payload["eventModel"].keys():
            full_k = f"eventModel.{k}"
            if full_k not in expected_dl_paths:
                issues.append({
                    "severity": "warning",
                    "field": full_k,
                    "message": f"La propiedad '{full_k}' se envía en el dataLayer pero la etiqueta '{tag_name}' en GTM no la recoge.",
                })

    has_errors = any(i["severity"] == "error" for i in issues)
    has_warnings = any(i["severity"] == "warning" for i in issues)

    if has_errors:
        status = "ERROR"
    elif has_warnings:
        status = "WARNING"
    else:
        status = "OK"

    return {
        "index": event_record["index"],
        "event_name": ev_name,
        "timestamp": event_record.get("timestamp", ""),
        "url": event_record.get("url") or payload.get("page_location") or payload.get("url") or event_record.get("origin", "URL desconocida"),
        "origin": event_record.get("origin", ""),
        "is_ga4_tracked": True,
        "is_system_event": False,
        "tag_name": tag_name,
        "status": status,
        "issues": issues,
        "param_results": param_results,
        "computed_values": computed_values,
        "payload": payload,
    }


def deduplicate_audited_events(audited: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplica los eventos auditados agrupando aquellos que presentan exactamente el mismo
    evento, estado e incidencias, registrando todas las URLs donde se ha detectado y el número de ocurrencias.
    """
    groups: Dict[str, Dict[str, Any]] = {}
    dedup_list: List[Dict[str, Any]] = []

    for item in audited:
        raw_url = item.get("url") or item.get("origin") or "URL desconocida"
        if item["status"] == "OK":
            fp = f"{item['event_name']}__OK__{raw_url}"
        else:
            issues_sig = "||".join(
                sorted(f"{i['severity']}:{i['field']}:{i['message']}" for i in item.get("issues", []))
            )
            fp = f"{item['event_name']}__{item['status']}__{issues_sig}"

        if fp not in groups:
            clone = dict(item)
            clone["occurrences"] = 1
            clone["occurrence_indices"] = [item["index"]]
            clone["detected_urls"] = {raw_url: 1}
            groups[fp] = clone
            dedup_list.append(clone)
        else:
            existing = groups[fp]
            existing["occurrences"] += 1
            existing["occurrence_indices"].append(item["index"])
            existing["detected_urls"][raw_url] = existing["detected_urls"].get(raw_url, 0) + 1

    return dedup_list


def analyze_events_dataset(
    raw_events_json: Any,
    gtm_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Analiza todos los eventos de un JSON contra la especificación de GTM y genera estadísticas globales.
    """
    records = extract_events_from_input(raw_events_json)
    audited = [audit_single_event(r, gtm_spec) for r in records]
    deduplicated = deduplicate_audited_events(audited)

    ga4_events = [a for a in audited if a["is_ga4_tracked"]]
    dedup_ga4 = [a for a in deduplicated if a["is_ga4_tracked"]]
    untracked_custom = [a for a in audited if not a["is_ga4_tracked"] and not a["is_system_event"]]
    system_events = [a for a in audited if a["is_system_event"]]

    ok_count = sum(1 for a in ga4_events if a["status"] == "OK")
    warn_count = sum(1 for a in ga4_events if a["status"] == "WARNING")
    err_count = sum(1 for a in ga4_events if a["status"] == "ERROR")

    unique_warn_count = sum(1 for a in dedup_ga4 if a["status"] == "WARNING")
    unique_err_count = sum(1 for a in dedup_ga4 if a["status"] == "ERROR")

    # Resumen por tipo de evento configurado en GTM
    by_event_type: Dict[str, Dict[str, Any]] = {}
    for ev_name, rule in gtm_spec.get("event_rules", {}).items():
        matching = [a for a in ga4_events if a["event_name"] == ev_name]
        matching_dedup = [a for a in dedup_ga4 if a["event_name"] == ev_name]
        by_event_type[ev_name] = {
            "event_name": ev_name,
            "tag_name": rule["tag_name"],
            "expected_params": [
                f"{p['parameter']} (opc.)" if p.get("optional") else p["parameter"]
                for p in rule["parameters"]
            ],
            "total_captured": len(matching),
            "ok": sum(1 for m in matching if m["status"] == "OK"),
            "warning": sum(1 for m in matching if m["status"] == "WARNING"),
            "error": sum(1 for m in matching if m["status"] == "ERROR"),
            "unique_warning": sum(1 for m in matching_dedup if m["status"] == "WARNING"),
            "unique_error": sum(1 for m in matching_dedup if m["status"] == "ERROR"),
        }

    return {
        "container_name": gtm_spec.get("container_name"),
        "public_id": gtm_spec.get("public_id"),
        "total_pushes": len(records),
        "total_ga4_events": len(ga4_events),
        "ok_count": ok_count,
        "warning_count": warn_count,
        "error_count": err_count,
        "unique_warning_count": unique_warn_count,
        "unique_error_count": unique_err_count,
        "untracked_custom_count": len(untracked_custom),
        "system_events_count": len(system_events),
        "by_event_type": by_event_type,
        "audited_events": audited,
        "deduplicated_events": deduplicated,
    }


# =====================================================================
# AUDITOR AUTÓNOMO CON PLAYWRIGHT (RASTREO + INTERACCIÓN SEGURA)
# =====================================================================
AUTONOMOUS_INIT_SCRIPT = """
(() => {
  if (window.__dlaAutonomousInstalled) return;
  window.__dlaAutonomousInstalled = true;
  window.__dlaCaptured = window.__dlaCaptured || [];
  window.__dlaCurrentAction = 'page_load';
  window.__dlaObservedTargets = [];

  // Interceptar IntersectionObserver para saber exactamente qué nodos del DOM
  // están asociados a impresiones de view_item_list y view_promotion
  if (typeof window.IntersectionObserver === 'function') {
    const OrigIO = window.IntersectionObserver;
    window.IntersectionObserver = function(callback, options) {
      const instance = new OrigIO(callback, options);
      const origObserve = instance.observe;
      instance.observe = function(targetEl) {
        try {
          if (targetEl && targetEl.nodeType === 1) {
            targetEl.setAttribute('data-dla-io-observed', '1');
            window.__dlaObservedTargets.push(targetEl);
          }
        } catch (e) {}
        return origObserve.apply(this, arguments);
      };
      return instance;
    };
    window.IntersectionObserver.prototype = OrigIO.prototype;
  }

  const safeClone = (obj) => {
    try { return JSON.parse(JSON.stringify(obj)); }
    catch (e) { return null; }
  };

  const recordItem = (item, originType) => {
    if (!item || typeof item !== 'object') return;
    const cloned = safeClone(item);
    if (!cloned) return;
    const evName = cloned.event ? String(cloned.event) : 'unnamed_push';
    const entry = {
      timestamp: new Date().toISOString(),
      url: window.location.href,
      origin: window.__dlaCurrentAction || originType || 'dataLayer.push',
      eventName: evName,
      explicitEvent: cloned.event ? String(cloned.event) : null,
      hasEventKey: 'event' in cloned,
      data: cloned
    };
    window.__dlaCaptured.push(entry);
    if (typeof window.__onAutonomousDlPush === 'function') {
      try { window.__onAutonomousDlPush(entry); } catch (err) {}
    }
  };

  const hookDL = (dl) => {
    if (!dl || dl.__dla_hooked) return;
    for (let i = 0; i < dl.length; i++) {
      recordItem(dl[i], 'initial_state');
    }
    const origPush = dl.push;
    dl.push = function(...args) {
      args.forEach((arg) => recordItem(arg, 'dataLayer.push'));
      return origPush.apply(this, args);
    };
    Object.defineProperty(dl, '__dla_hooked', {
      value: true,
      enumerable: false,
      configurable: true
    });
  };

  let currentDL = window.dataLayer || [];
  hookDL(currentDL);

  Object.defineProperty(window, 'dataLayer', {
    configurable: true,
    enumerable: true,
    get: function() { return currentDL; },
    set: function(newVal) {
      currentDL = newVal;
      if (Array.isArray(newVal)) {
        hookDL(newVal);
      }
    }
  });
})();
"""


def parse_urls_from_text(raw_text: str) -> List[str]:
    """
    Extrae una lista limpia de URLs válidas (http/https) a partir de un texto multilínea o separado por comas/punto y coma.
    Ignora líneas vacías y comentarios que empiecen por '#'.
    """
    urls: List[str] = []
    seen = set()
    for line in raw_text.splitlines():
        line_clean = line.strip()
        if not line_clean or line_clean.startswith("#"):
            continue
        # Soportar también separación por comas o punto y coma en una misma línea
        for part in re.split(r"[,;\s]+", line_clean):
            u = part.strip()
            if u.startswith(("http://", "https://")) and u not in seen:
                seen.add(u)
                urls.append(u)
    return urls


def run_autonomous_audit(
    start_url: Optional[str] = None,
    url_list: Optional[List[str]] = None,
    discover_links: bool = True,
    max_pages: int = 3,
    max_clicks_per_page: int = 12,
    headless: bool = True,
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Navega autónomamente usando Playwright:
      - Si se pasa `url_list` con `discover_links=False`, visita exactamente la lista de URLs indicada.
      - Si `discover_links=True`, además de las URLs iniciales, descubre enlaces internos del mismo dominio hasta `max_pages`.
      1. Inyecta el interceptor de dataLayer antes de que cargue cada página.
      2. Acepta el banner de cookies (OneTrust / CMP) si aparece.
      3. Realiza scroll progresivo para disparar eventos de visibilidad (view_item_list, view_promotion, impression).
      4. Interactúa con botones, pestañas y CTAs (bloqueando la navegación saliente durante la fase de clics)
         para disparar eventos de clic (select_item, select_promotion, add_to_cart, begin_checkout, services, funnel_step)
         y registra qué elemento exacto disparó cada evento.
    Devuelve un diccionario compatible con `analyze_events_dataset`.
    """
    from urllib.parse import urlparse
    from playwright.sync_api import sync_playwright

    captured_events: List[Dict[str, Any]] = []
    visited_urls: List[str] = []
    actions_log: List[str] = []

    def normalize_url(u: str) -> str:
        p = urlparse(u)
        clean_path = p.path.rstrip("/") or "/"
        query_part = f"?{p.query}" if p.query else ""
        return f"{p.scheme}://{p.netloc}{clean_path}{query_part}"

    seed_urls: List[str] = []
    if url_list:
        seed_urls.extend([u.strip() for u in url_list if u and u.strip()])
    if start_url and start_url.strip() and start_url.strip() not in seed_urls:
        seed_urls.insert(0, start_url.strip())

    if not seed_urls:
        return {
            "exportedAt": "",
            "visitedUrls": [],
            "actionsLog": ["⚠️ No se proporcionó ninguna URL válida para auditar."],
            "totalEventsExported": 0,
            "auditedEvents": [],
        }

    allowed_domains = {urlparse(u).netloc.lower() for u in seed_urls if urlparse(u).netloc}
    queue: List[str] = list(seed_urls)
    seen_normalized = {normalize_url(u) for u in seed_urls}
    total_limit = len(seed_urls) if (url_list and not discover_links) else max(max_pages, len(seed_urls))

    def log_step(msg: str) -> None:
        actions_log.append(msg)
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        context.add_init_script(AUTONOMOUS_INIT_SCRIPT)
        page = context.new_page()

        def on_dl_push(entry: Dict[str, Any]) -> None:
            if isinstance(entry, dict) and "data" in entry:
                captured_events.append(entry)

        page.expose_function("__onAutonomousDlPush", on_dl_push)

        while queue and len(visited_urls) < total_limit:
            target_url = queue.pop(0)
            visited_urls.append(target_url)
            page_num = len(visited_urls)
            log_step(f"[{page_num}/{total_limit}] Navegando a: {target_url}")

            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2000)
            except Exception as e:
                log_step(f"⚠️ Error al cargar {target_url}: {e}")
                continue

            # 1. Aceptar cookies automáticamente si aparece OneTrust u otro CMP
            try:
                cookie_selectors = [
                    "#onetrust-accept-btn-handler",
                    "button:has-text('Aceptar todas')",
                    "button:has-text('Aceptar')",
                ]
                for c_sel in cookie_selectors:
                    loc = page.locator(c_sel).first
                    if loc.count() > 0 and loc.is_visible(timeout=800):
                        page.evaluate("window.__dlaCurrentAction = 'accept_cookies'")
                        loc.click(timeout=2000)
                        log_step("🍪 Banner de cookies aceptado automáticamente.")
                        page.wait_for_timeout(1200)
                        break
            except Exception:
                pass

            # 2. Scroll progresivo lento de arriba abajo para activar todos los IntersectionObservers
            #    que disparan view_item_list y view_promotion en carruseles, banners y parrillas de tarifas
            try:
                page.evaluate("window.__dlaCurrentAction = 'scroll_visibilidad'")
                scroll_steps = 8
                for step_i in range(1, scroll_steps + 1):
                    pct = step_i / scroll_steps
                    page.evaluate(
                        f"window.scrollTo({{top: Math.floor(document.body.scrollHeight * {pct}), behavior: 'smooth'}})"
                    )
                    page.wait_for_timeout(650)
                page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                page.wait_for_timeout(500)
            except Exception:
                pass

            # 3. Extraer enlaces internos del mismo dominio para la cola de rastreo (si discover_links está activo)
            if discover_links and len(visited_urls) + len(queue) < total_limit * 3:
                try:
                    hrefs = page.evaluate(
                        """() => Array.from(document.querySelectorAll('a[href]'))
                                      .map(a => a.href)
                                      .filter(h => h && !h.startsWith('javascript:') && !h.startsWith('tel:') && !h.startsWith('mailto:'))"""
                    )
                    for h in hrefs:
                        parsed_h = urlparse(h)
                        if parsed_h.netloc.lower() in allowed_domains and parsed_h.scheme in ("http", "https"):
                            norm_h = normalize_url(h)
                            if norm_h not in seen_normalized and not any(
                                norm_h.lower().endswith(ext) for ext in (".pdf", ".jpg", ".png", ".svg", ".zip")
                            ):
                                seen_normalized.add(norm_h)
                                queue.append(h)
                except Exception:
                    pass

            # 4. Fase de interacción autónoma priorizando elementos de view_item_list y view_promotion
            if max_clicks_per_page > 0:
                try:
                    # Instalar protector en fase de burbuja y también interceptar History API (pushState/replaceState)
                    # para que los clics en tarjetas de React/Next.js disparen select_item / select_promotion sin desmontar el DOM
                    guard_js = """() => {
                        if (!window.__dlaNavGuardInstalled) {
                            window.__dlaNavGuardInstalled = true;
                            document.addEventListener('click', (e) => {
                                if (!window.__dlaBlockNav) return;
                                const a = e.target.closest('a');
                                if (a) {
                                    e.preventDefault();
                                }
                            }, false);
                            document.addEventListener('submit', (e) => {
                                if (window.__dlaBlockNav) {
                                    e.preventDefault();
                                }
                            }, false);
                            window.open = function() { return null; };
                            const origPushState = history.pushState;
                            const origReplaceState = history.replaceState;
                            history.pushState = function(...args) {
                                if (window.__dlaBlockNav) return;
                                return origPushState.apply(this, args);
                            };
                            history.replaceState = function(...args) {
                                if (window.__dlaBlockNav) return;
                                return origReplaceState.apply(this, args);
                            };
                        }
                        window.__dlaBlockNav = true;
                    }"""
                    page.evaluate(guard_js)

                    # Seleccionar equitativamente candidatos de:
                    #  A) Bloques de promoción (view_promotion -> select_promotion)
                    #  B) Bloques de listado de productos/tarifas (view_item_list -> select_item)
                    candidates = page.evaluate(
                        """(maxCount) => {
                            const captured = window.__dlaCaptured || [];
                            const itemTokens = new Set();
                            const promoTokens = new Set();

                            const addTokens = (str, targetSet) => {
                                if (!str) return;
                                String(str)
                                    .replace(/^(pack_|service_|catalogo_|banner_)/i, '')
                                    .split(/[\\s_\\-+]+/)
                                    .map(w => w.trim().toLowerCase())
                                    .filter(w => w.length >= 4 && !['desktop', 'mobile', 'home', 'masmovil', 'galeria', 'bundle'].includes(w))
                                    .forEach(w => targetSet.add(w));
                            };

                            captured.forEach((entry) => {
                                const d = entry && entry.data;
                                if (!d || !d.eventModel) return;
                                const em = d.eventModel;
                                if (d.event === 'view_promotion') {
                                    addTokens(em.promotion_name, promoTokens);
                                    addTokens(em.creative_name, promoTokens);
                                    addTokens(em.creative_slot, promoTokens);
                                }
                                if (d.event === 'view_item_list' && Array.isArray(em.items)) {
                                    em.items.forEach((it) => {
                                        if (it && it.item_name) addTokens(it.item_name, itemTokens);
                                    });
                                }
                            });

                            const ctaRegex = /(lo quiero|ver oferta|contratar|configurar|me interesa|ll[aá]mame|te llamamos|comprar|añadir|seleccionar|más info|ver detalle|lo quiero|ver más|descúbrelo)/i;
                            const navSkipRegex = /^(particulares|empresas|autónomos|ayuda|blog|soy cliente|mi cuenta|acceso|login|tienda|cobertura|quiénes somos|aviso legal|privacidad|cookies)$/i;

                            const selector = [
                                '[data-dla-io-observed] a, [data-dla-io-observed] button, [data-dla-io-observed] [role="button"], [data-dla-io-observed] [class*="MuiButton"], [data-dla-io-observed] [class*="btn"]',
                                '[class*="promo"] a, [class*="promo"] button, [class*="banner"] a, [class*="banner"] button, [class*="hero"] a, [class*="hero"] button, [class*="slide"] a, [class*="slide"] button, [class*="swiper"] a, [class*="swiper"] button',
                                '[class*="card"] a, [class*="card"] button, [class*="tarif"] a, [class*="tarif"] button, [class*="rate"] a, [class*="rate"] button',
                                '[class*="MuiButtonBase-root"], [class*="MuiButton-root"], [class*="btn"], [role="button"]',
                                'a[href], button'
                            ].join(', ');

                            const rawEls = Array.from(document.querySelectorAll(selector));
                            const promoList = [];
                            const itemList = [];
                            const otherList = [];
                            const seenContainers = new Set();

                            const getCardContext = (el) => {
                                const semantic = el.closest('[data-dla-io-observed], [class*="promo"], [class*="banner"], [class*="hero"], [class*="swiper-slide"], [class*="slide"], [class*="card"], [class*="tarif"], article, section');
                                if (semantic) return semantic;
                                let curr = el.parentElement;
                                for (let depth = 0; depth < 5 && curr && curr !== document.body; depth++) {
                                    const t = (curr.innerText || '').trim();
                                    if (t.length >= 25 && t.length <= 450) return curr;
                                    curr = curr.parentElement;
                                }
                                return el.parentElement || el;
                            };

                            rawEls.forEach((el, idx) => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                if (rect.width < 15 || rect.height < 15 || style.visibility === 'hidden' || style.display === 'none') return;
                                if (el.id && el.id.toLowerCase().includes('onetrust')) return;
                                if (el.closest('#onetrust-consent-sdk, footer, header, nav, [class*="footerMenu"], [class*="header"], [class*="navbar"]')) return;

                                const imgAlt = el.querySelector('img') ? (el.querySelector('img').getAttribute('alt') || '') : '';
                                const hrefVal = el.getAttribute('href') || '';
                                const fallbackHrefLabel = hrefVal && hrefVal !== '#' && !hrefVal.startsWith('javascript:')
                                    ? 'Enlace ' + hrefVal.replace(/^https?:\\/\\/[^/]+/i, '').slice(0, 40)
                                    : '';
                                const txt = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || imgAlt || el.value || fallbackHrefLabel || '')
                                    .trim()
                                    .replace(/\\s+/g, ' ')
                                    .slice(0, 70);
                                if (!txt || navSkipRegex.test(txt)) return;

                                const container = getCardContext(el);
                                const containerText = container ? (container.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 180) : txt;
                                const containerCls = container ? (container.className || '').toString().toLowerCase() : '';
                                const elCls = (el.className || '').toString().toLowerCase();
                                const combinedCls = containerCls + ' ' + elCls;
                                const lowerContext = (containerText + ' ' + txt + ' ' + hrefVal).toLowerCase();

                                // Agrupar por tarjeta/banner para probar distintos productos y promociones
                                const cardSig = `${el.tagName}:${txt.toLowerCase().slice(0, 25)}::${hrefVal.slice(0, 35)}::${containerText.slice(0, 60).toLowerCase()}`;
                                if (seenContainers.has(cardSig)) return;
                                seenContainers.add(cardSig);

                                let promoScore = 0;
                                let itemScore = 0;

                                if (/(promo|banner|hero|swiper|carousel|slide|campaign|destacad)/.test(combinedCls)) {
                                    promoScore += 45;
                                }
                                promoTokens.forEach((tk) => {
                                    if (lowerContext.includes(tk)) promoScore += 30;
                                });

                                if (/(card|tarif|product|rate|pack|bundle|item|catalogo|comparador|bono|prepago|fibra|movil)/.test(combinedCls) || /(tarif|bono|gb|fibra|movil|prepago|contrato)/.test(lowerContext)) {
                                    itemScore += 45;
                                }
                                itemTokens.forEach((tk) => {
                                    if (lowerContext.includes(tk)) itemScore += 25;
                                });

                                if (el.closest('[data-dla-io-observed]')) {
                                    promoScore += 20;
                                    itemScore += 20;
                                }
                                if (ctaRegex.test(txt)) {
                                    promoScore += 25;
                                    itemScore += 25;
                                }

                                const autoId = `dla_${idx}`;
                                el.setAttribute('data-dla-autoid', autoId);

                                if (promoScore >= itemScore && promoScore >= 30) {
                                    promoList.push({
                                        autoId,
                                        tag: el.tagName.toLowerCase(),
                                        text: txt,
                                        href: hrefVal,
                                        category: 'view_promotion -> select_promotion',
                                        score: promoScore
                                    });
                                } else if (itemScore > 0) {
                                    itemList.push({
                                        autoId,
                                        tag: el.tagName.toLowerCase(),
                                        text: txt,
                                        href: hrefVal,
                                        category: 'view_item_list -> select_item',
                                        score: itemScore
                                    });
                                } else {
                                    otherList.push({
                                        autoId,
                                        tag: el.tagName.toLowerCase(),
                                        text: txt,
                                        href: hrefVal,
                                        category: 'interacción general',
                                        score: 10
                                    });
                                }
                            });

                            promoList.sort((a, b) => b.score - a.score);
                            itemList.sort((a, b) => b.score - a.score);

                            // Intercalar clics entre promociones (view_promotion) y listas de productos (view_item_list)
                            const balanced = [];
                            let pIdx = 0, iIdx = 0;
                            while (balanced.length < maxCount && (pIdx < promoList.length || iIdx < itemList.length)) {
                                if (pIdx < promoList.length) balanced.push(promoList[pIdx++]);
                                if (balanced.length < maxCount && iIdx < itemList.length) balanced.push(itemList[iIdx++]);
                            }
                            for (let o = 0; o < otherList.length && balanced.length < maxCount; o++) {
                                balanced.push(otherList[o]);
                            }
                            return balanced;
                        }""",
                        max_clicks_per_page,
                    )

                    page.evaluate("window.__dlaBlockNav = true")
                    for cand_idx, cand in enumerate(candidates):
                        tag_name = cand["tag"]
                        text_val = cand["text"]
                        href_val = cand.get("href") or ""
                        label_desc = f"clic en <{tag_name}> «{text_val}» [{cand['category']}]"
                        try:
                            # Localizar tanto por data-dla-autoid como por texto/href por si hubo re-render o page.goto
                            auto_id = cand["autoId"]
                            loc = page.locator(f'[data-dla-autoid="{auto_id}"]').first
                            if loc.count() == 0:
                                if href_val:
                                    loc = page.locator(f'{tag_name}[href="{href_val}"]').first
                                if loc.count() == 0 and text_val and not text_val.startswith("Enlace "):
                                    loc = page.locator(f'{tag_name}:has-text({json.dumps(text_val[:25])})').first
                            if loc.count() == 0:
                                continue

                            before_count = len(captured_events)
                            page.evaluate(f"window.__dlaCurrentAction = {json.dumps(label_desc)}")
                            try:
                                loc.scroll_into_view_if_needed(timeout=1500)
                            except Exception:
                                pass
                            page.wait_for_timeout(200)

                            # Disparar click nativo en JS sobre el elemento (evita navegación MPA de <a> mientras ejecuta onClick de React/MUI/GTM)
                            clicked_ok = loc.evaluate(
                                """(el) => {
                                    const preventNav = (ev) => {
                                        if (ev.target && ev.target.closest && ev.target.closest('a')) {
                                            ev.preventDefault();
                                        }
                                    };
                                    window.addEventListener('click', preventNav, true);
                                    try {
                                        el.click();
                                        return true;
                                    } finally {
                                        window.removeEventListener('click', preventNav, true);
                                    }
                                }"""
                            )
                            if not clicked_ok:
                                continue
                            page.wait_for_timeout(550)

                            # Si aun así cambió la URL por window.location, volvemos a target_url y re-hidratamos
                            if normalize_url(page.url) != normalize_url(target_url):
                                page.wait_for_timeout(600)
                                page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                                page.wait_for_timeout(1200)
                                page.evaluate(guard_js)

                            after_count = len(captured_events)
                            new_evs = [
                                e.get("eventName")
                                for e in captured_events[before_count:after_count]
                                if e.get("eventName") and not str(e.get("eventName")).startswith("gtm.")
                            ]
                            if new_evs:
                                log_step(f"  ⚡ {label_desc} -> disparó: {', '.join(new_evs)}")
                            else:
                                log_step(f"  🖱️ {label_desc} -> sin evento de GA4 asociado")

                            # Cerrar posibles modales abiertos tras el clic
                            page.keyboard.press("Escape")
                        except Exception:
                            pass
                    page.evaluate("window.__dlaBlockNav = false")
                except Exception as e:
                    log_step(f"  ℹ️ Aviso en fase de interacción: {e}")

        browser.close()

    log_step(f"✅ Auditoría autónoma finalizada: {len(visited_urls)} página(s) visitadas, {len(captured_events)} eventos capturados.")
    return {
        "exportedAt": "",
        "visitedUrls": visited_urls,
        "actionsLog": actions_log,
        "totalEventsExported": len(captured_events),
        "auditedEvents": captured_events,
    }


def print_cli_report(report: Dict[str, Any]) -> None:
    """Imprime un informe claro por consola cuando se ejecuta desde CLI (con deduplicación de errores)."""
    print("=" * 80)
    print(f" AUDITORÍA DE EVENTOS GA4 vs GTM ({report['container_name']} - {report['public_id']})")
    print("=" * 80)
    print(f"Total pushes analizados : {report['total_pushes']}")
    print(f"Eventos GA4 detectados  : {report['total_ga4_events']}")
    print(f"  [OK] Correctos        : {report['ok_count']}")
    print(f"  [WARN] Con avisos     : {report['unique_warning_count']}")
    print(f"  [ERR] Con errores     : {report['unique_error_count']}")
    print(f"Eventos no mapeados GTM : {report['untracked_custom_count']}")
    print(f"Eventos sistema (gtm.*) : {report['system_events_count']}")
    print("-" * 80)
    print("RESUMEN POR TIPO DE EVENTO GTM:")
    for ev_name, stats in report["by_event_type"].items():
        if stats["total_captured"] > 0:
            print(
                f"  - {ev_name:<20} | Capturados: {stats['total_captured']:<3} "
                f"| OK: {stats['ok']:<3} | WARN: {stats['unique_warning']:<3} "
                f"| ERR: {stats['unique_error']:<3} "
                f"| Tag: {stats['tag_name']}"
            )
    print("-" * 80)

    problem_events = [
        e for e in report["deduplicated_events"]
        if e["is_ga4_tracked"] and e["status"] in ("ERROR", "WARNING")
    ]
    if not problem_events:
        print("¡No se encontraron errores ni advertencias en los eventos GA4 capturados!")
    else:
        print(f"DETALLE DE INCIDENCIAS DEDUPLICADAS ({len(problem_events)} errores/avisos únicos):")
        for ev in problem_events:
            urls_map = ev.get("detected_urls", {ev.get("url", "URL desconocida"): 1})
            urls_str = ", ".join(urls_map.keys())
            print(f"\n  [#{ev['index']}] Evento: {ev['event_name']} ({ev['status']}) -> Tag: {ev['tag_name']}")
            print(f"       URL(s) detectadas: {urls_str}")
            for iss in ev["issues"]:
                sev = iss["severity"].upper()
                print(f"       [{sev}] {iss['field']}: {iss['message']}")
    print("=" * 80)


def generate_html_report(report: Dict[str, Any], deduplicate: bool = True) -> str:
    """
    Genera el informe visual e interactivo en HTML (con el mismo diseño limpio que la extensión de Chrome),
    listo para abrir en el navegador o imprimir en PDF.
    """
    import html as html_lib
    from datetime import datetime

    def esc(val: Any) -> str:
        return html_lib.escape(str(val if val is not None else ""))

    gen_date = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    container_name = report.get("container_name", "GTM")
    public_id = report.get("public_id", "GTM-XXXX")

    source_list = report["deduplicated_events"] if deduplicate else report["audited_events"]
    ga4_filtered = [a for a in source_list if a.get("is_ga4_tracked")]

    summary_rows = []
    for ev_name, t in report.get("by_event_type", {}).items():
        if t.get("total_captured", 0) <= 0:
            continue
        warn_val = t["unique_warning"] if deduplicate else t["warning"]
        err_val = t["unique_error"] if deduplicate else t["error"]
        if err_val > 0:
            row_badge = '<span class="badge badge-err">Con errores</span>'
        elif warn_val > 0:
            row_badge = '<span class="badge badge-warn">Con avisos</span>'
        else:
            row_badge = '<span class="badge badge-ok">Correcto</span>'

        summary_rows.append(
            f"""
            <tr>
              <td><code class="ev-code">{esc(ev_name)}</code></td>
              <td>{esc(t.get("tag_name", ""))}</td>
              <td class="num">{t["total_captured"]}</td>
              <td class="num ok-txt">{t["ok"]}</td>
              <td class="num warn-txt">{warn_val}</td>
              <td class="num err-txt">{err_val}</td>
              <td>{row_badge}</td>
              <td class="params-cell">{esc(", ".join(t.get("expected_params", [])))}</td>
            </tr>
            """
        )

    cards_html_list = []
    for a in ga4_filtered:
        st = a.get("status", "OK")
        st_class = "card-err" if st == "ERROR" else "card-warn" if st == "WARNING" else "card-ok"
        issues = a.get("issues", [])
        if st == "ERROR":
            st_badge = f'<span class="badge badge-err">❌ Error ({len(issues)})</span>'
        elif st == "WARNING":
            st_badge = f'<span class="badge badge-warn">⚠️ Aviso ({len(issues)})</span>'
        elif st == "OK":
            st_badge = '<span class="badge badge-ok">✅ Correcto</span>'
        else:
            st_badge = '<span class="badge badge-neutral">⚪ Sin etiqueta de GA4</span>'

        urls_map = a.get("detected_urls") or {a.get("url") or "URL desconocida": 1}
        urls_items = "".join(
            f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(u)}</a></li>'
            for u in urls_map.keys()
        )

        origin_str = a.get("origin", "")
        origin_badge = (
            f'<span class="occ-badge">⚡ {esc(origin_str)}</span>'
            if origin_str and origin_str not in ("dataLayer", "dataLayer.push", "imported_json")
            else ""
        )

        if issues:
            iss_items = "".join(
                f'<li class="iss-{esc(iss.get("severity", "error"))}"><strong>{esc(iss.get("field", ""))}:</strong> {esc(iss.get("message", ""))}</li>'
                for iss in issues
            )
            issues_html = f"""
              <div class="issues-section">
                <h4>⚠️ Problemas detectados ({len(issues)})</h4>
                <ul class="issues-list">{iss_items}</ul>
              </div>
            """
        else:
            issues_html = '<div class="ok-banner">✓ Todos los parámetros requeridos por la etiqueta de GTM se han enviado correctamente.</div>'

        param_rows = []
        for p in a.get("param_results", []):
            p_st = p.get("status", "")
            if p_st == "OK":
                st_icon = '<span class="badge badge-ok">✓ Correcto</span>'
            elif p_st == "OPTIONAL_OMITTED":
                st_icon = '<span class="badge badge-neutral">◌ Opcional (no enviado)</span>'
            else:
                st_icon = f'<span class="badge badge-err">✗ {esc(p_st)}</span>'

            val = p.get("value")
            if isinstance(val, (dict, list)):
                val_str = json.dumps(val, indent=2, ensure_ascii=False)
            elif val is not None:
                val_str = str(val)
            else:
                val_str = "—"

            param_rows.append(
                f"""
                <tr>
                  <td><strong>{esc(p.get("parameter", ""))}</strong></td>
                  <td><code>{esc(p.get("dl_path", ""))}</code></td>
                  <td>{st_icon}</td>
                  <td><pre class="val-pre">{esc(val_str)}</pre></td>
                </tr>
                """
            )

        params_block = ""
        if param_rows:
            open_attr = "open" if st != "OK" else ""
            params_block = f"""
              <details class="details-block" {open_attr}>
                <summary>📋 Ver tabla de parámetros evaluados ({len(param_rows)})</summary>
                <table class="params-table">
                  <thead>
                    <tr>
                      <th>Parámetro de GA4</th>
                      <th>Variable / ruta de dataLayer</th>
                      <th>Estado</th>
                      <th>Valor recibido</th>
                    </tr>
                  </thead>
                  <tbody>{"".join(param_rows)}</tbody>
                </table>
              </details>
            """

        payload_str = json.dumps(a.get("payload", {}), indent=2, ensure_ascii=False)
        cards_html_list.append(
            f"""
            <div class="event-card {st_class}" data-status="{esc(st)}" data-event="{esc(a.get("event_name", ""))}">
              <div class="event-card-header">
                <div class="ev-title">
                  <span class="ev-idx">#{a.get("index", "")}</span>
                  <span class="ev-name">{esc(a.get("event_name", ""))}</span>
                  {st_badge}
                  {origin_badge}
                </div>
                <div class="ev-tag">🏷️ Etiqueta de GTM: <strong>{esc(a.get("tag_name") or "Sin etiqueta")}</strong></div>
              </div>
              <div class="event-card-body">
                <div class="urls-box">
                  <strong>🌐 URL donde se ha detectado:</strong>
                  <ul class="urls-list">{urls_items}</ul>
                </div>
                {issues_html}
                {params_block}
                <details class="details-block">
                  <summary>💻 Ver payload JSON original del dataLayer</summary>
                  <pre class="json-pre">{esc(payload_str)}</pre>
                </details>
              </div>
            </div>
            """
        )

    kpi_warn = report["unique_warning_count"] if deduplicate else report["warning_count"]
    kpi_err = report["unique_error_count"] if deduplicate else report["error_count"]

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Informe de auditoría de GA4 — {esc(container_name)} ({esc(public_id)})</title>
  <style>
    :root {{
      --bg: #f8fafc;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #64748b;
      --border: #e2e8f0;
      --ok: #10b981;
      --ok-bg: #ecfdf5;
      --warn: #f59e0b;
      --warn-bg: #fffbeb;
      --err: #ef4444;
      --err-bg: #fef2f2;
      --blue: #2563eb;
      --orange: #ff6600;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 28px 20px;
    }}
    .container {{ max-width: 1140px; margin: 0 auto; }}
    .report-header {{
      background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
      color: #fff;
      padding: 24px 28px;
      border-radius: 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      margin-bottom: 22px;
      box-shadow: 0 4px 16px rgba(15, 23, 42, 0.12);
    }}
    .report-header h1 {{ font-size: 21px; font-weight: 700; margin-bottom: 4px; }}
    .report-header p {{ font-size: 13px; color: #cbd5e1; }}
    .print-btn {{
      background: var(--orange);
      color: #fff;
      border: none;
      padding: 9px 16px;
      border-radius: 8px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
    }}
    .print-btn:hover {{ opacity: 0.92; }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 14px;
      margin-bottom: 24px;
    }}
    .kpi-box {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px 20px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .kpi-box .val {{ font-size: 26px; font-weight: 800; display: block; }}
    .kpi-box .lbl {{ font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase; }}
    .kpi-ok .val {{ color: var(--ok); }}
    .kpi-warn .val {{ color: var(--warn); }}
    .kpi-err .val {{ color: var(--err); }}
    .section-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .section-title {{ font-size: 16px; font-weight: 700; margin-bottom: 14px; color: #1e293b; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }}
    th {{ background: #f1f5f9; font-size: 11px; text-transform: uppercase; color: #475569; font-weight: 700; }}
    .num {{ font-weight: 700; text-align: center; }}
    .ok-txt {{ color: var(--ok); }}
    .warn-txt {{ color: var(--warn); }}
    .err-txt {{ color: var(--err); }}
    .ev-code {{ background: #eff6ff; color: #1d4ed8; padding: 2px 6px; border-radius: 4px; font-weight: 700; }}
    .params-cell {{ font-size: 12px; color: var(--muted); }}
    .badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 700;
    }}
    .badge-ok {{ background: var(--ok-bg); color: #047857; border: 1px solid #a7f3d0; }}
    .badge-warn {{ background: var(--warn-bg); color: #b45309; border: 1px solid #fde68a; }}
    .badge-err {{ background: var(--err-bg); color: #b91c1c; border: 1px solid #fecaca; }}
    .badge-neutral {{ background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }}
    .filter-bar {{
      display: flex;
      gap: 12px;
      margin-bottom: 16px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .filter-bar input, .filter-bar select {{
      padding: 8px 12px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 13px;
      background: #fff;
    }}
    .filter-bar input {{ flex: 1; min-width: 220px; }}
    .event-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-left: 5px solid #cbd5e1;
      border-radius: 10px;
      margin-bottom: 16px;
      overflow: hidden;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .event-card.card-err {{ border-left-color: var(--err); }}
    .event-card.card-warn {{ border-left-color: var(--warn); }}
    .event-card.card-ok {{ border-left-color: var(--ok); }}
    .event-card-header {{
      padding: 14px 18px;
      background: #f8fafc;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .ev-title {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .ev-idx {{ background: #e2e8f0; color: #334155; font-weight: 700; font-size: 11px; padding: 2px 7px; border-radius: 5px; }}
    .ev-name {{ font-family: Consolas, monospace; font-size: 15px; font-weight: 700; color: #0f172a; }}
    .occ-badge {{ background: #e0e7ff; color: #3730a3; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; }}
    .ev-tag {{ font-size: 12px; color: var(--muted); }}
    .event-card-body {{ padding: 16px 18px; display: flex; flex-direction: column; gap: 12px; }}
    .urls-box {{
      background: #f1f5f9;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 12px;
    }}
    .urls-list {{ margin-top: 4px; padding-left: 18px; }}
    .urls-list a {{ color: var(--blue); text-decoration: none; word-break: break-all; }}
    .urls-list a:hover {{ text-decoration: underline; }}
    .issues-section {{
      background: var(--err-bg);
      border: 1px solid #fecaca;
      padding: 12px 16px;
      border-radius: 8px;
    }}
    .issues-section h4 {{ font-size: 13px; color: #991b1b; margin-bottom: 6px; }}
    .issues-list {{ padding-left: 18px; font-size: 13px; color: #7f1d1d; }}
    .issues-list li {{ margin-bottom: 4px; }}
    .issues-list li.iss-warning {{ color: #92400e; }}
    .ok-banner {{
      background: var(--ok-bg);
      border: 1px solid #a7f3d0;
      color: #065f46;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
    }}
    .details-block {{ border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; background: #fafafa; }}
    .details-block summary {{ cursor: pointer; font-weight: 600; font-size: 12px; color: #334155; }}
    .params-table {{ margin-top: 10px; background: #fff; }}
    .val-pre, .json-pre {{
      font-family: Consolas, monospace;
      font-size: 11px;
      white-space: pre-wrap;
      word-break: break-all;
      background: #0f172a;
      color: #e2e8f0;
      padding: 8px 10px;
      border-radius: 6px;
      margin-top: 6px;
      max-height: 240px;
      overflow-y: auto;
    }}
    .val-pre {{ background: #f8fafc; color: #0f172a; padding: 4px 6px; margin-top: 0; border: 1px solid #e2e8f0; }}
    @media print {{
      body {{ background: #fff; padding: 0; }}
      .print-btn, .filter-bar {{ display: none !important; }}
      .event-card {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="report-header">
      <div>
        <h1>📊 Informe de auditoría de eventos de GA4 frente a GTM</h1>
        <p>Contenedor de GTM: <strong>{esc(container_name)} ({esc(public_id)})</strong> &bull; Generado: {esc(gen_date)} &bull; Modo: {"Deduplicado por error" if deduplicate else "Listado completo"}</p>
      </div>
      <button class="print-btn" onclick="window.print()">🖨️ Imprimir / guardar en PDF</button>
    </header>

    <section class="kpi-grid">
      <div class="kpi-box">
        <span class="val">{report["total_ga4_events"]}</span>
        <span class="lbl">Eventos de GA4 analizados</span>
      </div>
      <div class="kpi-box kpi-ok">
        <span class="val">{report["ok_count"]}</span>
        <span class="lbl">✅ Eventos correctos</span>
      </div>
      <div class="kpi-box kpi-warn">
        <span class="val">{kpi_warn}</span>
        <span class="lbl">⚠️ Avisos</span>
      </div>
      <div class="kpi-box kpi-err">
        <span class="val">{kpi_err}</span>
        <span class="lbl">❌ Errores</span>
      </div>
    </section>

    <section class="section-card">
      <h2 class="section-title">📌 Resumen por tipo de evento (según etiquetas de GTM)</h2>
      <table>
        <thead>
          <tr>
            <th>Evento</th>
            <th>Etiqueta de GTM</th>
            <th style="text-align:center;">Capturados</th>
            <th style="text-align:center;">✅ Correctos</th>
            <th style="text-align:center;">⚠️ Avisos</th>
            <th style="text-align:center;">❌ Errores</th>
            <th>Estado</th>
            <th>Parámetros esperados en GTM</th>
          </tr>
        </thead>
        <tbody>{"".join(summary_rows)}</tbody>
      </table>
    </section>

    <section class="section-card">
      <h2 class="section-title">🔎 Detalle de eventos e incidencias ({len(ga4_filtered)})</h2>
      <div class="filter-bar">
        <input type="text" id="searchBox" placeholder="Filtrar por evento, URL, acción, parámetro o mensaje de error..." oninput="filterCards()">
        <select id="statusSelect" onchange="filterCards()">
          <option value="ALL">Todos los estados</option>
          <option value="ERROR">Solo errores (❌)</option>
          <option value="WARNING">Solo avisos (⚠️)</option>
          <option value="OK">Solo correctos (✅)</option>
        </select>
      </div>
      <div id="cardsWrapper">
        {"".join(cards_html_list)}
      </div>
    </section>
  </div>

  <script>
    function filterCards() {{
      const q = document.getElementById('searchBox').value.toLowerCase();
      const st = document.getElementById('statusSelect').value;
      document.querySelectorAll('.event-card').forEach((card) => {{
        const matchSt = st === 'ALL' || card.dataset.status === st;
        const matchTxt = !q || card.innerText.toLowerCase().includes(q);
        card.style.display = matchSt && matchTxt ? 'block' : 'none';
      }});
    }}
  </script>
</body>
</html>"""


def generate_csv_report(report: Dict[str, Any], deduplicate: bool = True) -> str:
    """Genera el informe en CSV con BOM UTF-8 para abrir directamente en Excel."""
    def csv_esc(val: Any) -> str:
        s = str(val if val is not None else "").replace('"', '""')
        return f'"{s}"'

    headers = [
        "Índice",
        "Fecha y hora",
        "Acción / origen",
        "Evento",
        "Etiqueta de GTM",
        "Estado en GA4",
        "URL detectadas",
        "Total de incidencias",
        "Parámetros correctos",
        "Parámetros faltantes o inválidos",
        "Detalle de incidencias",
        "Valores de parámetros de GTM",
        "Payload JSON de muestra",
    ]

    source_list = report["deduplicated_events"] if deduplicate else report["audited_events"]
    ga4_filtered = [a for a in source_list if a.get("is_ga4_tracked")]

    rows = []
    for a in ga4_filtered:
        p_res = a.get("param_results", [])
        ok_params = ", ".join(p["parameter"] for p in p_res if p.get("status") == "OK")
        fail_params = ", ".join(
            f"{p['parameter']} ({p['status']})"
            for p in p_res
            if p.get("status") not in ("OK", "OPTIONAL_OMITTED")
        )
        issues_detail = " | ".join(
            f"[{iss.get('severity', '').upper()}] {iss.get('field', '')}: {iss.get('message', '')}"
            for iss in a.get("issues", [])
        )
        param_vals = " ; ".join(
            f"{p['parameter']}={json.dumps(p['value'], ensure_ascii=False) if isinstance(p.get('value'), (dict, list)) else (p.get('value') if p.get('value') is not None else 'NULL')}"
            for p in p_res
        )
        urls_map = a.get("detected_urls") or {a.get("url") or "URL desconocida": 1}
        urls_str = " | ".join(urls_map.keys())

        rows.append(
            ",".join([
                str(a.get("index", "")),
                csv_esc(a.get("timestamp", "")),
                csv_esc(a.get("origin", "")),
                csv_esc(a.get("event_name", "")),
                csv_esc(a.get("tag_name") or "Sin etiqueta de GA4"),
                csv_esc(a.get("status", "")),
                csv_esc(urls_str),
                str(len(a.get("issues", []))),
                csv_esc(ok_params),
                csv_esc(fail_params),
                csv_esc(issues_detail),
                csv_esc(param_vals),
                csv_esc(json.dumps(a.get("payload", {}), ensure_ascii=False)),
            ])
        )

    return "\uFEFF" + "\r\n".join([",".join(headers)] + rows)


# =====================================================================
# INTERFAZ STREAMLIT (Se ejecuta si se lanza con `streamlit run`)
# =====================================================================
def run_streamlit_app() -> None:
    import streamlit as st
    import pandas as pd

    st.set_page_config(
        page_title="Analizador de eventos de GA4 y GTM",
        page_icon="🔍",
        layout="wide",
    )

    st.title("🔍 Analizador de eventos de GA4 frente al contenedor de GTM")
    st.markdown(
        "Valida que todos los eventos enviados al `dataLayer` contengan los parámetros exactos "
        "definidos en las etiquetas de **Google Tag Manager** (`eventModel.*` y estructura de `items`)."
    )

    # Sidebar: Configuración del contenedor GTM
    st.sidebar.header("⚙️ 1. Contenedor de GTM (reglas)")
    gtm_source = st.sidebar.radio(
        "Origen del contenedor de GTM:",
        options=[
            "Usar contenedor de referencia por defecto",
            "Subir otro archivo JSON de GTM",
        ],
    )

    gtm_spec = None
    if gtm_source == "Usar contenedor de referencia por defecto":
        gtm_spec = get_builtin_default_gtm_spec()
        st.sidebar.success("Cargado: `Contenedor de referencia (integrado por defecto)`")
    else:
        uploaded_gtm = st.sidebar.file_uploader("Subir exportación JSON de GTM", type=["json"], key="gtm_up")
        if uploaded_gtm:
            gtm_spec = parse_gtm_container(json.load(uploaded_gtm))

    if not gtm_spec:
        st.info("Por favor, selecciona o sube un archivo de contenedor de GTM válido para continuar.")
        return

    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Eventos de GA4 configurados:** `{len(gtm_spec['event_rules'])}`")

    with st.expander("📋 Ver catálogo de eventos y parámetros requeridos según GTM", expanded=False):
        rules_rows = []
        for ev_name, rule in gtm_spec["event_rules"].items():
            params_str = ", ".join(
                f"{p['parameter']} ({'JS: ' + p['gtm_value'] if p['is_computed'] else p['dl_path']})"
                for p in rule["parameters"]
            )
            u_props_str = ", ".join(f"{u['name']} ({u['dl_path']})" for u in rule["user_properties"]) or "-"
            rules_rows.append({
                "Evento (activador)": ev_name,
                "Etiqueta de GTM": rule["tag_name"],
                "Parámetros requeridos": params_str,
                "Propiedades de usuario": u_props_str,
            })
        st.dataframe(pd.DataFrame(rules_rows), use_container_width=True, hide_index=True)

    # Sección principal: Pestañas para auditoría autónoma o subida de JSON
    tab_auto, tab_json = st.tabs([
        "🤖 Auditoría autónoma en vivo (Playwright)",
        "📂 Cargar JSON de eventos",
    ])

    datasets_to_analyze: List[Tuple[str, Any]] = []

    with tab_auto:
        st.subheader("🤖 Rastreador y auditor autónomo de eventos de GA4")
        st.markdown(
            "El robot abre un navegador real con **Playwright**, inyecta el interceptor del `dataLayer` antes de que cargue la web, "
            "acepta las cookies, hace *scroll*, recorre las páginas e interactúa con los botones y tarjetas para validar todos los eventos que se disparen."
        )

        auto_mode = st.radio(
            "Modo de selección de páginas:",
            options=[
                "📋 Listado personalizado de URL (pegar lista o subir archivo)",
                "🕷️ Rastreo automático desde una URL inicial (descubre enlaces internos)",
            ],
            horizontal=True,
            key="auto_mode_radio",
        )

        custom_urls_parsed: List[str] = []
        auto_url = ""
        auto_max_pages = 2
        discover_links_flag = False

        if auto_mode.startswith("📋"):
            col_list_txt, col_list_up = st.columns([2, 1])
            with col_list_txt:
                raw_urls_text = st.text_area(
                    "Escribe o pega las URL que deseas auditar (una por línea):",
                    value="https://www.masmovil.es/\nhttps://www.masmovil.es/fibra-optica\nhttps://www.masmovil.es/tarifas-moviles",
                    height=135,
                    key="auto_urls_textarea",
                )
            with col_list_up:
                uploaded_urls_file = st.file_uploader(
                    "O sube un archivo con URL (.txt / .csv):",
                    type=["txt", "csv"],
                    key="auto_urls_file",
                )
                auto_max_clicks = st.number_input(
                    "Clics a probar por cada URL:",
                    min_value=0,
                    max_value=40,
                    value=10,
                    step=2,
                    key="auto_max_clicks_list",
                )

            combined_text = raw_urls_text or ""
            if uploaded_urls_file is not None:
                try:
                    file_txt = uploaded_urls_file.getvalue().decode("utf-8", errors="ignore")
                    combined_text = combined_text + "\n" + file_txt
                except Exception as e:
                    st.error(f"Error leyendo el archivo de URL: {e}")

            custom_urls_parsed = parse_urls_from_text(combined_text)
            st.caption(f"🔗 **{len(custom_urls_parsed)}** URL válidas listas para analizar.")
            auto_max_pages = len(custom_urls_parsed)
            discover_links_flag = False
        else:
            c_url, c_pages, c_clicks = st.columns([3, 1, 1])
            with c_url:
                auto_url = st.text_input(
                    "URL inicial a auditar:",
                    value="https://www.masmovil.es/",
                    key="auto_url_input",
                )
            with c_pages:
                auto_max_pages = st.number_input(
                    "Máx. páginas a recorrer:",
                    min_value=1,
                    max_value=25,
                    value=2,
                    step=1,
                    key="auto_max_pages",
                )
            with c_clicks:
                auto_max_clicks = st.number_input(
                    "Clics por página:",
                    min_value=0,
                    max_value=40,
                    value=10,
                    step=2,
                    key="auto_max_clicks",
                )
            discover_links_flag = True

        run_auto_btn = st.button("🚀 Iniciar auditoría autónoma ahora", type="primary")
        if run_auto_btn:
            if auto_mode.startswith("📋") and not custom_urls_parsed:
                st.warning("Introduce al menos una URL válida (con `http://` o `https://`).")
            elif not auto_mode.startswith("📋") and not auto_url.strip():
                st.warning("Introduce una URL inicial válida.")
            else:
                log_box = st.empty()
                live_logs: List[str] = []

                def update_log(msg: str) -> None:
                    live_logs.append(msg)
                    log_box.code("\n".join(live_logs), language="text")

                label_desc = (
                    f"{len(custom_urls_parsed)} URL de la lista"
                    if auto_mode.startswith("📋")
                    else auto_url.strip()
                )
                with st.spinner(f"Navegando e interactuando autónomamente ({label_desc})..."):
                    auto_dataset = run_autonomous_audit(
                        start_url=auto_url.strip() if not auto_mode.startswith("📋") else None,
                        url_list=custom_urls_parsed if auto_mode.startswith("📋") else None,
                        discover_links=discover_links_flag,
                        max_pages=int(auto_max_pages),
                        max_clicks_per_page=int(auto_max_clicks),
                        headless=True,
                        progress_callback=update_log,
                    )
                    st.session_state["last_autonomous_dataset"] = (
                        f"Auditoría autónoma ({label_desc})",
                        auto_dataset,
                    )

        if "last_autonomous_dataset" in st.session_state:
            lbl, ds = st.session_state["last_autonomous_dataset"]
            datasets_to_analyze.append((lbl, ds))
            if ds.get("actionsLog"):
                with st.expander("📜 Ver registro detallado de navegación e interacciones del robot", expanded=False):
                    st.code("\n".join(ds["actionsLog"]), language="text")

    with tab_json:
        st.subheader("📂 Cargar JSON de eventos para analizar")

        col_up1, col_up2 = st.columns([2, 1])
        with col_up1:
            uploaded_events_files = st.file_uploader(
                "Sube uno o varios archivos JSON (exportación de la extensión o array de eventos del dataLayer)",
                type=["json"],
                accept_multiple_files=True,
            )
        with col_up2:
            # Permitir también probar con archivos JSON locales del proyecto
            local_jsons = sorted([
                f for f in os.listdir(".")
                if f.endswith(".json") and not f.startswith(("token", "client_secret", "found_target", "audit_templates", "ws_changes"))
            ])
            selected_local = st.selectbox(
                "O selecciona un JSON de prueba del proyecto:",
                options=["-- Ninguno --"] + local_jsons,
            )

        if uploaded_events_files:
            for uf in uploaded_events_files:
                try:
                    datasets_to_analyze.append((uf.name, json.load(uf)))
                except Exception as e:
                    st.error(f"Error leyendo {uf.name}: {e}")
        elif selected_local != "-- Ninguno --":
            try:
                with open(selected_local, "r", encoding="utf-8") as f:
                    datasets_to_analyze.append((selected_local, json.load(f)))
            except Exception as e:
                st.error(f"Error leyendo {selected_local}: {e}")

    if not datasets_to_analyze:
        st.info("👆 Pulsa **«🚀 Iniciar auditoría autónoma ahora»** en la primera pestaña o sube un archivo JSON en la segunda pestaña.")
        return

    for file_label, raw_ev_data in datasets_to_analyze:
        st.markdown("---")
        st.header(f"📊 Resultado del análisis: `{file_label}`")
        report = analyze_events_dataset(raw_ev_data, gtm_spec)

        # KPIs principales
        dedup_mode = st.checkbox(
            "🔁 Deduplicar errores repetidos (evita notificar el mismo error dos veces si se pasa varias veces por la misma página y agrupa las URL donde se detectó)",
            value=True,
            key=f"dedup_chk_{file_label}",
        )

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total de envíos (pushes)", report["total_pushes"])
        k2.metric("Eventos de GA4", report["total_ga4_events"])
        k3.metric("✅ Correctos", report["ok_count"])
        k4.metric(
            "⚠️ Con avisos",
            report["unique_warning_count"] if dedup_mode else report["warning_count"],
        )
        k5.metric(
            "❌ Con errores",
            report["unique_error_count"] if dedup_mode else report["error_count"],
        )

        # Resumen por tipo de evento
        st.subheader("📌 Estado por tipo de evento (según GTM)")
        type_rows = []
        for ev_name, st_info in report["by_event_type"].items():
            type_rows.append({
                "Evento": ev_name,
                "Etiqueta de GTM": st_info["tag_name"],
                "Capturados": st_info["total_captured"],
                "✅ Correctos": st_info["ok"],
                "⚠️ Avisos": st_info["unique_warning"] if dedup_mode else st_info["warning"],
                "❌ Errores": st_info["unique_error"] if dedup_mode else st_info["error"],
                "Parámetros esperados": ", ".join(st_info["expected_params"]),
            })
        df_types = pd.DataFrame(type_rows)

        only_captured = st.checkbox("Mostrar solo tipos de eventos presentes en el archivo", value=True, key=f"chk_{file_label}")
        if only_captured:
            df_types = df_types[df_types["Capturados"] > 0]
        st.dataframe(df_types, use_container_width=True, hide_index=True)

        # Filtros de inspección detallada
        st.subheader("🔎 Inspección detallada de eventos")
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            status_filter = st.multiselect(
                "Filtrar por estado:",
                options=["ERROR", "WARNING", "OK", "UNTRACKED", "IGNORED"],
                default=["ERROR", "WARNING", "OK"],
                key=f"st_f_{file_label}",
            )
        with f_col2:
            available_ev_names = sorted(list({e["event_name"] for e in report["audited_events"]}))
            ev_filter = st.multiselect(
                "Filtrar por nombre de evento:",
                options=available_ev_names,
                default=[],
                placeholder="Todos los eventos",
                key=f"ev_f_{file_label}",
            )
        with f_col3:
            search_txt = st.text_input("Buscar en payload, URL o mensaje de error:", key=f"srch_{file_label}")

        source_events = report["deduplicated_events"] if dedup_mode else report["audited_events"]

        filtered_events = [
            e for e in source_events
            if e["status"] in status_filter
            and (not ev_filter or e["event_name"] in ev_filter)
            and (
                not search_txt
                or search_txt.lower() in json.dumps(e["payload"], ensure_ascii=False).lower()
                or search_txt.lower() in str(e.get("url", "")).lower()
                or any(search_txt.lower() in iss["message"].lower() for iss in e["issues"])
            )
        ]

        st.caption(f"Mostrando **{len(filtered_events)}** de **{len(source_events)}** registros ({'deduplicados' if dedup_mode else 'sin deduplicar'}).")

        for ev in filtered_events:
            badge = (
                "🔴 Error" if ev["status"] == "ERROR"
                else "🟡 Aviso" if ev["status"] == "WARNING"
                else "🟢 Correcto" if ev["status"] == "OK"
                else "⚪ Sin etiqueta de GA4" if ev["status"] == "UNTRACKED"
                else "⚫ Sistema"
            )
            urls_map = ev.get("detected_urls", {ev.get("url", "URL desconocida"): 1})
            primary_url = next(iter(urls_map.keys()), ev.get("url", "-"))
            url_str = f" | 🌐 `{primary_url}`" + (f" (+{len(urls_map)-1} URL)" if len(urls_map) > 1 else "")
            header_title = f"#{ev['index']} — **{ev['event_name']}** [{badge}] — Etiqueta: `{ev['tag_name'] or 'N/A'}`{url_str}"

            with st.expander(header_title, expanded=(ev["status"] == "ERROR")):
                st.markdown("**🌐 URL donde se ha detectado este evento/error:**")
                for u_path in urls_map.keys():
                    st.markdown(f"- `{u_path}`")

                if ev["issues"]:
                    st.markdown("**Incidencias detectadas:**")
                    for iss in ev["issues"]:
                        if iss["severity"] == "error":
                            st.error(f"**{iss['field']}**: {iss['message']}")
                        elif iss["severity"] == "warning":
                            st.warning(f"**{iss['field']}**: {iss['message']}")
                        else:
                            st.info(f"**{iss['field']}**: {iss['message']}")
                else:
                    st.success("Todos los parámetros requeridos por GTM están presentes y son válidos.")

                c_left, c_right = st.columns([3, 2])
                with c_left:
                    if ev["param_results"]:
                        st.markdown("**Verificación de parámetros de la etiqueta de GTM:**")
                        p_df = pd.DataFrame([
                            {
                                "Parámetro de GA4": f"{pr['parameter']} (opcional)" if pr.get("optional") else pr["parameter"],
                                "Ruta en dataLayer": pr["dl_path"],
                                "Estado": (
                                    "✅ Correcto" if pr["status"] == "OK"
                                    else "⚪ Opcional (omitido)" if pr["status"] == "OPTIONAL_OMITTED"
                                    else f"❌ {pr['status']}"
                                ),
                                "Valor enviado": (
                                    json.dumps(pr["value"], ensure_ascii=False)
                                    if isinstance(pr["value"], (list, dict))
                                    else str(pr["value"]) if pr["value"] is not None else "NULL / MISSING"
                                ),
                                "Nota": pr["note"],
                            }
                            for pr in ev["param_results"]
                        ])
                        st.dataframe(p_df, use_container_width=True, hide_index=True)
                with c_right:
                    st.markdown("**Payload JSON del evento:**")
                    st.json(ev["payload"])

        # Botones para descargar informe visual HTML, CSV y JSON
        html_doc = generate_html_report(report, deduplicate=dedup_mode)
        csv_doc = generate_csv_report(report, deduplicate=dedup_mode)
        clean_slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", os.path.splitext(file_label)[0]).strip("_") or "reporte"

        dl_c1, dl_c2, dl_c3 = st.columns(3)
        with dl_c1:
            st.download_button(
                label="📄 Descargar informe visual (HTML)",
                data=html_doc,
                file_name=f"informe_auditoria_ga4_{clean_slug}.html",
                mime="text/html",
                type="primary",
                use_container_width=True,
                key=f"dl_html_{file_label}",
            )
        with dl_c2:
            st.download_button(
                label="📊 Descargar informe en CSV",
                data=csv_doc.encode("utf-8"),
                file_name=f"informe_auditoria_ga4_{clean_slug}.csv",
                mime="text/csv",
                use_container_width=True,
                key=f"dl_csv_{file_label}",
            )
        with dl_c3:
            st.download_button(
                label="📥 Descargar informe completo (JSON)",
                data=json.dumps(report, indent=2, ensure_ascii=False),
                file_name=f"informe_auditoria_ga4_{clean_slug}.json",
                mime="application/json",
                use_container_width=True,
                key=f"dl_btn_{file_label}",
            )

        with st.expander("👁️ Vista previa integrada del informe visual (HTML)", expanded=True):
            import streamlit.components.v1 as components
            components.html(html_doc, height=820, scrolling=True)


def is_running_in_streamlit() -> bool:
    if "streamlit" not in sys.modules:
        return False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx() is not None
    except Exception:
        return False


def main() -> None:
    if is_running_in_streamlit():
        run_streamlit_app()
        return

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Analizador de eventos de GA4 enviados desde dataLayer según contenedor de GTM (.json)"
    )
    parser.add_argument(
        "events_json",
        nargs="?",
        help="Ruta al archivo JSON con los eventos a analizar",
    )
    parser.add_argument(
        "--url",
        nargs="+",
        help="Una o varias URL para ejecutar una auditoría autónoma en vivo con Playwright",
    )
    parser.add_argument(
        "--urls-file",
        help="Ruta a un archivo .txt o .csv con el listado de URL a analizar autónomamente (una por línea)",
    )
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Si se indica junto con --url, descubre enlaces internos adicionales hasta --max-pages",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=2,
        help="Número máximo de páginas a recorrer en modo autónomo (por defecto: 2)",
    )
    parser.add_argument(
        "--max-clicks",
        type=int,
        default=10,
        help="Número máximo de interacciones/clics por página en modo autónomo (por defecto: 10)",
    )
    parser.add_argument(
        "--gtm",
        default=DEFAULT_GTM_PATH,
        help="Ruta al archivo JSON del contenedor de GTM (por defecto usa el contenedor de referencia integrado)",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Guardar el informe detallado de auditoría en un archivo JSON",
    )
    parser.add_argument(
        "--html",
        help="Ruta donde guardar el informe visual en HTML (si se ejecuta con --url o --urls-file y no se indica, se genera 'informe_auditoria_ga4.html' automáticamente)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="No abrir automáticamente en el navegador el informe HTML generado desde CLI",
    )

    args = parser.parse_args()

    if not args.events_json and not args.url and not args.urls_file:
        print("Uso por línea de comandos:")
        print("  1) Auditar un archivo JSON:")
        print("     python ga4_event_analyzer.py <archivo_eventos.json> [--gtm ruta_gtm.json] [-o informe.json]")
        print("  2) Auditoría autónoma de un listado de URL:")
        print("     python ga4_event_analyzer.py --url https://www.masmovil.es/ https://www.masmovil.es/fibra-optica [-o informe.json]")
        print("     python ga4_event_analyzer.py --urls-file urls.txt [--max-clicks 10] [-o informe.json]")
        print("  3) Rastreo autónomo descubriendo enlaces internos:")
        print("     python ga4_event_analyzer.py --url https://www.masmovil.es/ --crawl --max-pages 5 [-o informe.json]")
        print("\nPara abrir la interfaz visual web en tu navegador ejecuta:")
        print("  streamlit run ga4_event_analyzer.py")
        return

    if not args.gtm:
        gtm_spec = get_builtin_default_gtm_spec()
    elif os.path.exists(args.gtm):
        with open(args.gtm, "r", encoding="utf-8") as f:
            gtm_spec = parse_gtm_container(json.load(f))
    else:
        print(f"Error: No se encuentra el archivo GTM en '{args.gtm}'", file=sys.stderr)
        sys.exit(1)

    if args.url or args.urls_file:
        target_urls: List[str] = []
        if args.url:
            for u_item in args.url:
                target_urls.extend(parse_urls_from_text(u_item))
        if args.urls_file:
            if not os.path.exists(args.urls_file):
                print(f"Error: No se encuentra el archivo de URL en '{args.urls_file}'", file=sys.stderr)
                sys.exit(1)
            with open(args.urls_file, "r", encoding="utf-8") as uf:
                target_urls.extend(parse_urls_from_text(uf.read()))

        # Eliminar duplicados manteniendo el orden
        unique_urls = list(dict.fromkeys(target_urls))
        discover_flag = bool(args.crawl or (len(unique_urls) == 1 and args.max_pages > 1 and not args.urls_file))

        print("=" * 80)
        print(f" 🤖 INICIANDO AUDITORÍA AUTÓNOMA EN {len(unique_urls)} URL(S)")
        print("=" * 80)
        events_data = run_autonomous_audit(
            url_list=unique_urls,
            discover_links=discover_flag,
            max_pages=args.max_pages if discover_flag else len(unique_urls),
            max_clicks_per_page=args.max_clicks,
            headless=True,
            progress_callback=lambda m: print(f"  {m}"),
        )
    else:
        if not os.path.exists(args.events_json):
            print(f"Error: No se encuentra el archivo de eventos en '{args.events_json}'", file=sys.stderr)
            sys.exit(1)
        with open(args.events_json, "r", encoding="utf-8") as f:
            events_data = json.load(f)

    report = analyze_events_dataset(events_data, gtm_spec)
    print_cli_report(report)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nInforme JSON guardado en: {args.output}")

    html_out_path = args.html
    if not html_out_path and (args.url or args.urls_file):
        html_out_path = f"informe_auditoria_ga4_{report['public_id']}.html"

    if html_out_path:
        html_content = generate_html_report(report, deduplicate=True)
        abs_html_path = os.path.abspath(html_out_path)
        with open(abs_html_path, "w", encoding="utf-8") as hf:
            hf.write(html_content)
        print(f"📄 Informe visual HTML generado en: {abs_html_path}")
        if not args.no_open:
            try:
                import webbrowser
                webbrowser.open(f"file:///{abs_html_path.replace(os.sep, '/')}")
            except Exception:
                pass


if __name__ == "__main__":
    main()
