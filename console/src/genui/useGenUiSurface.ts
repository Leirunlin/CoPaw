/** Subscribe a component to a surface model; re-renders on every fold. */
import { useSyncExternalStore } from "react";
import { getModel } from "./store";
import { SurfaceModel } from "./surfaceModel";

export function useGenUiSurface(
  runKey: string,
  surfaceId: string,
): SurfaceModel {
  const model = getModel(runKey, surfaceId);
  useSyncExternalStore(model.subscribe, model.getSnapshot, model.getSnapshot);
  return model;
}
