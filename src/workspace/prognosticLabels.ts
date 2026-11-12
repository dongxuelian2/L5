import { t as tr } from "../i18n";
import type { ForecastStatus, Method } from "./prognosticTypes";

const methodNames = { linear: "Linear trend", stochastic: "Stochastic drift" };
const statusNames: Record<ForecastStatus, string> = {
  ok: "Forecast available",
  insufficient_data: "There are too few usable measurements to fit this model.",
  not_identifiable: "This model is not identifiable from the selected history.",
  numerical_failure: "The model could not complete the numerical fit.",
  threshold_reached: "The failure threshold has already been reached at the cutoff.",
  beyond_horizon: "The median first-passage time exceeds the forecast horizon.",
};

export function modelName(method: Method) { return tr(methodNames[method]); }
export function forecastStatus(status: ForecastStatus) { return tr(statusNames[status] || status); }
