import React from "react";
import { useLocation } from "react-router-dom";
import { GenUiSurface } from "../../../genui";

const TaskPlanPage: React.FC = () => {
  const path = new URLSearchParams(useLocation().search).get("path") || "";
  if (!path) {
    return (
      <div style={{ padding: 24 }}>
        Missing <code>?path=</code> query parameter.
      </div>
    );
  }
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <GenUiSurface surfaceId={`task:${path}`} compact={false} />
    </div>
  );
};

export default TaskPlanPage;
