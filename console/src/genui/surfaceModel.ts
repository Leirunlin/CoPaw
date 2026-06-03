/**
 * In-memory model of one A2UI surface: a flat component map (adjacency list)
 * keyed by id + a data model. Folds envelopes exactly like the backend mirror
 * and exposes a subscribe/getSnapshot interface for React's
 * `useSyncExternalStore`.
 */
import { pointerDelete, pointerGet, pointerUpsert } from "./dataModel";
import {
  Component,
  DynamicValue,
  Envelope,
  isPathRef,
} from "./types";

export class SurfaceModel {
  readonly surfaceId: string;
  catalogId = "";
  components = new Map<string, Component>();
  data: unknown = {};

  private version = 0;
  private listeners = new Set<() => void>();

  constructor(surfaceId: string) {
    this.surfaceId = surfaceId;
  }

  apply(env: Envelope): void {
    if (env.createSurface) {
      this.catalogId = env.createSurface.catalogId;
      // A fresh surface resets components/data.
      this.components.clear();
      this.data = {};
    } else if (env.updateComponents) {
      for (const comp of env.updateComponents.components) {
        if (comp.id) this.components.set(comp.id, comp);
      }
    } else if (env.updateDataModel) {
      const { path, value } = env.updateDataModel;
      const p = path || "/";
      this.data =
        value === undefined
          ? pointerDelete(this.data, p)
          : pointerUpsert(this.data, p, value);
    } else if (env.deleteSurface) {
      this.components.clear();
      this.data = {};
    }
    this.bump();
  }

  applyMany(envs: Envelope[]): void {
    for (const env of envs) this.apply(env);
  }

  get(id: string): Component | undefined {
    return this.components.get(id);
  }

  /** Resolve a DynamicValue: literal as-is, `{path}` via the data model. */
  resolve<T = unknown>(value: DynamicValue | undefined, fallback?: T): T {
    if (value === undefined) return fallback as T;
    if (isPathRef(value)) {
      return pointerGet(this.data, value.path, fallback) as T;
    }
    return value as T;
  }

  /** Write through a `{path}` binding into the local data model. */
  setBoundValue(binding: DynamicValue | undefined, value: unknown): void {
    if (!isPathRef(binding)) return;
    this.data = pointerUpsert(this.data, binding.path, value);
    this.bump();
  }

  // --- useSyncExternalStore plumbing ---
  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  };
  getSnapshot = (): number => this.version;

  private bump(): void {
    this.version += 1;
    this.listeners.forEach((cb) => {
      try {
        cb();
      } catch {
        /* ignore */
      }
    });
  }
}
