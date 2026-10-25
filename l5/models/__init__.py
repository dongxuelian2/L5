"""Explicit, versioned process models. No dynamic code or third-party discovery."""
from .triplens import TripLensModel
from .tanks import CoupledTankModel

MODELS = {model.id: model for model in (TripLensModel(), CoupledTankModel())}


def resolve(identity):
    try:
        return MODELS[identity]
    except (KeyError, TypeError):
        raise ValueError('Unknown process Model ID.') from None


def catalog():
    return [model.describe() for model in MODELS.values()]
