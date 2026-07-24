import { Form, Switch } from "@agentscope-ai/design";
import { Segmented } from "antd";
import { useTranslation } from "react-i18next";

export function VisualCompactSettings() {
  const { t } = useTranslation();

  return (
    <>
      <Form.Item
        label={t("agentConfig.visualCompactEnabled")}
        name={["light_context_config", "visual_compact_config", "enabled"]}
        valuePropName="checked"
      >
        <Switch size="small" />
      </Form.Item>

      <Form.Item
        initialValue="low"
        label={t("agentConfig.visualCompactEffort")}
        name={["light_context_config", "visual_compact_config", "effort"]}
      >
        <Segmented
          options={[
            {
              label: t("agentConfig.visualCompactLow"),
              value: "low",
            },
            {
              label: t("agentConfig.visualCompactMedium"),
              value: "medium",
            },
            {
              label: t("agentConfig.visualCompactHigh"),
              value: "high",
            },
          ]}
          size="small"
        />
      </Form.Item>
    </>
  );
}
