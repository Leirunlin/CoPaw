import { Card, Form, Switch } from "@agentscope-ai/design";
import { Segmented, Typography } from "antd";
import { useTranslation } from "react-i18next";
import styles from "../index.module.less";

type VisualCompactEffort = "low" | "medium" | "high";

const { Paragraph, Text } = Typography;
const effortDescriptionKey: Record<VisualCompactEffort, string> = {
  low: "agentConfig.visualCompactLowDescription",
  medium: "agentConfig.visualCompactMediumDescription",
  high: "agentConfig.visualCompactHighDescription",
};

export function VisualCompactCard() {
  const { t } = useTranslation();
  const enabled = Boolean(
    Form.useWatch(["light_context_config", "visual_compact_config", "enabled"]),
  );
  const effort = (Form.useWatch([
    "light_context_config",
    "visual_compact_config",
    "effort",
  ]) ?? "medium") as VisualCompactEffort;

  return (
    <Card
      className={styles.visualCompactCard}
      size="small"
      title={t("agentConfig.visualCompactTitle")}
    >
      <Paragraph type="secondary">
        {t("agentConfig.visualCompactDescription")}
      </Paragraph>

      <Form.Item
        label={t("agentConfig.visualCompactEnabled")}
        name={["light_context_config", "visual_compact_config", "enabled"]}
        valuePropName="checked"
      >
        <Switch />
      </Form.Item>

      {enabled && (
        <>
          <Form.Item
            initialValue="medium"
            label={t("agentConfig.visualCompactEffort")}
            name={["light_context_config", "visual_compact_config", "effort"]}
          >
            <Segmented
              aria-label={t("agentConfig.visualCompactEffort")}
              block
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
            />
          </Form.Item>
          <Paragraph className={styles.visualCompactEffortDescription}>
            {t(effortDescriptionKey[effort])}
          </Paragraph>
          <Text type="secondary">
            {t("agentConfig.visualCompactQualityNote")}
          </Text>
        </>
      )}

      <Paragraph
        className={styles.visualCompactCapabilityNote}
        type="secondary"
      >
        {t("agentConfig.visualCompactCapabilityNote")}
      </Paragraph>
    </Card>
  );
}
