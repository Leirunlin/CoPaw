/**
 * Native renderer for the vendored A2UI v0.10 catalog subset:
 * Text, Row, Column, List, Card, Divider, Button, CheckBox, TextField,
 * ChoicePicker, Icon. Keep this list in lock-step with the backend allowlist
 * (`qwenpaw.agents.genui.catalog.ALLOWED_COMPONENTS`).
 */
import React from "react";
import {
  Button,
  Card,
  Checkbox,
  Divider,
  Input,
  Select,
  Typography,
} from "antd";
import { SurfaceModel } from "./surfaceModel";
import { Component, DynamicValue } from "./types";

export interface RenderCtx {
  model: SurfaceModel;
  /** Fire a user action (sourceComponentId + already-resolved context). */
  onAction: (
    name: string,
    sourceComponentId: string,
    context: Record<string, unknown>,
  ) => void;
}

const HEADING_LEVEL: Record<string, 1 | 2 | 3 | 4 | 5> = {
  h1: 1,
  h2: 2,
  h3: 3,
  h4: 4,
  h5: 5,
};

/** Resolve every value in an action context (DynamicValue -> concrete). */
function resolveContext(
  model: SurfaceModel,
  context: Record<string, unknown> | undefined,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(context || {})) {
    out[k] = model.resolve(v as DynamicValue);
  }
  return out;
}

export function renderComponent(
  id: string,
  ctx: RenderCtx,
  seen: Set<string> = new Set(),
): React.ReactNode {
  if (seen.has(id)) return null; // guard against cycles
  const comp = ctx.model.get(id);
  if (!comp) return null;
  const next = new Set(seen);
  next.add(id);
  return (
    <ComponentNode key={id} comp={comp} ctx={ctx} seen={next} />
  );
}

const ComponentNode: React.FC<{
  comp: Component;
  ctx: RenderCtx;
  seen: Set<string>;
}> = ({ comp, ctx, seen }) => {
  const { model } = ctx;
  const childIds = (comp.children as string[] | undefined) || [];

  switch (comp.component) {
    case "Text": {
      const text = String(model.resolve(comp.text as DynamicValue, ""));
      const variant = (comp.variant as string) || "body";
      const level = HEADING_LEVEL[variant];
      if (level) {
        return (
          <Typography.Title level={level} style={{ margin: 0 }}>
            {text}
          </Typography.Title>
        );
      }
      if (variant === "caption") {
        return <Typography.Text type="secondary">{text}</Typography.Text>;
      }
      return <Typography.Text>{text}</Typography.Text>;
    }

    case "Row":
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            gap: 8,
            alignItems: alignToCss(comp.align as string) || "center",
          }}
        >
          {childIds.map((cid) => renderComponent(cid, ctx, seen))}
        </div>
      );

    case "Column":
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            alignItems: alignToCss(comp.align as string),
          }}
        >
          {childIds.map((cid) => renderComponent(cid, ctx, seen))}
        </div>
      );

    case "List":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {childIds.map((cid) => renderComponent(cid, ctx, seen))}
        </div>
      );

    case "Card":
      return (
        <Card size="small" style={{ marginBottom: 8 }}>
          {renderComponent(comp.child as string, ctx, seen)}
        </Card>
      );

    case "Divider":
      return <Divider style={{ margin: "8px 0" }} />;

    case "Button": {
      const action = comp.action as
        | { event?: { name?: string; context?: Record<string, unknown> } }
        | undefined;
      const variant = (comp.variant as string) || "default";
      return (
        <Button
          size="small"
          type={
            variant === "primary"
              ? "primary"
              : variant === "borderless"
                ? "text"
                : "default"
          }
          onClick={() => {
            const ev = action?.event;
            if (ev?.name) {
              ctx.onAction(
                ev.name,
                comp.id,
                resolveContext(model, ev.context),
              );
            }
          }}
        >
          {renderComponent(comp.child as string, ctx, seen)}
        </Button>
      );
    }

    case "CheckBox": {
      const checked = Boolean(model.resolve(comp.value as DynamicValue, false));
      const label = String(model.resolve(comp.label as DynamicValue, ""));
      return <Checkbox checked={checked}>{label}</Checkbox>;
    }

    case "TextField": {
      const value = String(model.resolve(comp.value as DynamicValue, ""));
      const label = comp.label
        ? String(model.resolve(comp.label as DynamicValue, ""))
        : undefined;
      return (
        <Input size="small" defaultValue={value} placeholder={label} readOnly />
      );
    }

    case "ChoicePicker": {
      const value = model.resolve<string | undefined>(
        comp.value as DynamicValue,
        undefined,
      );
      const options =
        (comp.options as { label?: string; value?: unknown }[] | undefined) ||
        [];
      return (
        <Select
          size="small"
          value={value}
          options={options.map((o) => ({
            label: String(o.label ?? o.value),
            value: o.value as string,
          }))}
          style={{ minWidth: 120 }}
        />
      );
    }

    case "Icon":
      return <span>{String(comp.name ?? comp.icon ?? "")}</span>;

    default:
      return null;
  }
};

function alignToCss(align?: string): string | undefined {
  switch (align) {
    case "start":
      return "flex-start";
    case "end":
      return "flex-end";
    case "center":
      return "center";
    case "stretch":
      return "stretch";
    default:
      return undefined;
  }
}
