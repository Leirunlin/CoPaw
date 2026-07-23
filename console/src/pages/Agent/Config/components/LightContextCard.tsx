import {
  Form,
  Card,
  Switch,
  Input,
  Collapse,
  Select,
  InputNumber,
} from "@agentscope-ai/design";
import { useTranslation } from "react-i18next";
import { SliderWithValue } from "./SliderWithValue";
import {
  calculateReserveThreshold,
  usesTieredToolResultSettings,
} from "./toolResultSettings";
import styles from "../index.module.less";

interface LightContextCardProps {
  maxInputLength: number;
}

// Retention windows longer than this many days trigger a (non-blocking)
// storage warning. 0 (keep forever) warns separately.
const HISTORY_RETENTION_LARGE_WARN_DAYS = 30;

// Evaluation-only knobs stay in the form schema for reproducible benchmarks,
// but the product surface intentionally exposes one opt-in switch with the
// pxpipe-aligned defaults.
// TODO: STALE: Remove the hidden tuning controls and this guard before the
// production release.
const SHOW_EXPERIMENTAL_VISUAL_COMPRESSION_TUNING = false;

export function LightContextCard({ maxInputLength }: LightContextCardProps) {
  const { t } = useTranslation();

  const compactThresholdRatio = Form.useWatch([
    "light_context_config",
    "context_compact_config",
    "compact_threshold_ratio",
  ]);
  const reserveThresholdRatio = Form.useWatch([
    "light_context_config",
    "context_compact_config",
    "reserve_threshold_ratio",
  ]);
  const contextStrategy =
    Form.useWatch(["light_context_config", "strategy"]) ?? "scroll";
  const showTieredToolResultSettings =
    usesTieredToolResultSettings(contextStrategy);

  // history_retention_days only applies to the scroll strategy.
  const isScrollStrategy = contextStrategy === "scroll";
  const historyRetentionDays = Form.useWatch([
    "light_context_config",
    "scroll_config",
    "history_retention_days",
  ]);
  // Warn (never block): 0 keeps history forever, a very large window eats disk.
  let historyRetentionWarning: string | null = null;
  if (
    isScrollStrategy &&
    historyRetentionDays !== undefined &&
    historyRetentionDays !== null
  ) {
    if (historyRetentionDays <= 0) {
      historyRetentionWarning = t(
        "agentConfig.historyRetentionDaysForeverWarning",
      );
    } else if (historyRetentionDays > HISTORY_RETENTION_LARGE_WARN_DAYS) {
      historyRetentionWarning = t(
        "agentConfig.historyRetentionDaysLargeWarning",
      );
    }
  }

  const compactThreshold = Math.floor(
    (maxInputLength ?? 0) * (compactThresholdRatio ?? 0.8),
  );
  const reserveThreshold = calculateReserveThreshold(
    maxInputLength ?? 0,
    reserveThresholdRatio ?? 0.1,
    contextStrategy,
  );

  return (
    <Card
      className={styles.formCard}
      title={t("agentConfig.lightContextTitle")}
    >
      <Form.Item
        label={t("agentConfig.dialogPath")}
        name={["light_context_config", "dialog_path"]}
        tooltip={t("agentConfig.dialogPathTooltip")}
      >
        <Input placeholder={t("agentConfig.dialogPathPlaceholder")} />
      </Form.Item>

      <Form.Item
        label={t("agentConfig.tokenCountEstimateDivisor")}
        name={["light_context_config", "token_count_estimate_divisor"]}
        rules={[
          {
            required: true,
            message: t("agentConfig.tokenCountEstimateDivisorRequired"),
          },
        ]}
        tooltip={t("agentConfig.tokenCountEstimateDivisorTooltip")}
      >
        <SliderWithValue
          min={2}
          max={5}
          step={0.25}
          marks={{ 2: "2", 3: "3", 4: "4", 5: "5" }}
        />
      </Form.Item>

      <Collapse
        items={[
          {
            key: "contextCompact",
            label: t("agentConfig.contextCompactCollapseLabel"),
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.contextCompactEnabled")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.contextCompactEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactRatio")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "compact_threshold_ratio",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t("agentConfig.contextCompactRatioRequired"),
                    },
                  ]}
                  tooltip={t("agentConfig.contextCompactRatioTooltip")}
                >
                  <SliderWithValue
                    min={0.1}
                    max={0.9}
                    step={0.01}
                    marks={{ 0.1: "0.1", 0.5: "0.5", 0.9: "0.9" }}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactThreshold")}
                  tooltip={t("agentConfig.contextCompactThresholdTooltip")}
                >
                  <Input
                    disabled
                    value={
                      compactThreshold > 0
                        ? compactThreshold.toLocaleString()
                        : ""
                    }
                    placeholder={t(
                      "agentConfig.contextCompactThresholdPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactReserveRatio")}
                  name={[
                    "light_context_config",
                    "context_compact_config",
                    "reserve_threshold_ratio",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t(
                        "agentConfig.contextCompactReserveRatioRequired",
                      ),
                    },
                  ]}
                  tooltip={t("agentConfig.contextCompactReserveRatioTooltip")}
                >
                  <SliderWithValue
                    min={0.01}
                    max={0.3}
                    step={0.01}
                    marks={{ 0.01: "0.01", 0.15: "0.15", 0.3: "0.3" }}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.contextCompactReserveThreshold")}
                  tooltip={t(
                    "agentConfig.contextCompactReserveThresholdTooltip",
                  )}
                >
                  <Input
                    disabled
                    value={
                      reserveThreshold > 0
                        ? reserveThreshold.toLocaleString()
                        : ""
                    }
                    placeholder={t(
                      "agentConfig.contextCompactReserveThresholdPlaceholder",
                    )}
                  />
                </Form.Item>

                {isScrollStrategy && (
                  <Form.Item
                    label={t("agentConfig.historyRetentionDays")}
                    name={[
                      "light_context_config",
                      "scroll_config",
                      "history_retention_days",
                    ]}
                    rules={[
                      {
                        required: true,
                        message: t("agentConfig.historyRetentionDaysRequired"),
                      },
                    ]}
                    tooltip={t("agentConfig.historyRetentionDaysTooltip")}
                    extra={
                      historyRetentionWarning ? (
                        <span style={{ color: "#faad14" }}>
                          {historyRetentionWarning}
                        </span>
                      ) : undefined
                    }
                  >
                    <InputNumber
                      min={0}
                      step={1}
                      precision={0}
                      style={{ width: "100%" }}
                    />
                  </Form.Item>
                )}
              </>
            ),
          },
          {
            key: "toolResultPruning",
            label: t("agentConfig.toolResultPruningCollapseLabel"),
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.toolResultCompactEnabled")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.toolResultCompactEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>

                {showTieredToolResultSettings && (
                  <>
                    <Form.Item
                      label={t("agentConfig.toolResultCompactRecentN")}
                      name={[
                        "light_context_config",
                        "tool_result_pruning_config",
                        "pruning_recent_n",
                      ]}
                      rules={[
                        {
                          required: true,
                          message: t(
                            "agentConfig.toolResultCompactRecentNRequired",
                          ),
                        },
                      ]}
                      tooltip={t("agentConfig.toolResultCompactRecentNTooltip")}
                    >
                      <SliderWithValue
                        min={1}
                        max={10}
                        step={1}
                        marks={{ 1: "1", 5: "5", 10: "10" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.toolResultCompactOldThreshold")}
                      name={[
                        "light_context_config",
                        "tool_result_pruning_config",
                        "pruning_old_msg_max_bytes",
                      ]}
                      rules={[
                        {
                          required: true,
                          message: t(
                            "agentConfig.toolResultCompactOldThresholdRequired",
                          ),
                        },
                      ]}
                      tooltip={t(
                        "agentConfig.toolResultCompactOldThresholdTooltip",
                      )}
                    >
                      <Input
                        placeholder={t(
                          "agentConfig.toolResultCompactOldThresholdPlaceholder",
                        )}
                      />
                    </Form.Item>
                  </>
                )}

                <Form.Item
                  label={t("agentConfig.toolResultCompactRecentThreshold")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "pruning_recent_msg_max_bytes",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t(
                        "agentConfig.toolResultCompactRecentThresholdRequired",
                      ),
                    },
                  ]}
                  tooltip={t(
                    "agentConfig.toolResultCompactRecentThresholdTooltip",
                  )}
                >
                  <Input
                    placeholder={t(
                      "agentConfig.toolResultCompactRecentThresholdPlaceholder",
                    )}
                  />
                </Form.Item>

                <Form.Item
                  label={t("agentConfig.toolResultCompactRetentionDays")}
                  name={[
                    "light_context_config",
                    "tool_result_pruning_config",
                    "offload_retention_days",
                  ]}
                  rules={[
                    {
                      required: true,
                      message: t(
                        "agentConfig.toolResultCompactRetentionDaysRequired",
                      ),
                    },
                  ]}
                  tooltip={t(
                    "agentConfig.toolResultCompactRetentionDaysTooltip",
                  )}
                >
                  <SliderWithValue
                    min={1}
                    max={365}
                    step={1}
                    marks={{ 1: "1", 30: "30", 365: "365" }}
                  />
                </Form.Item>

                {showTieredToolResultSettings && (
                  <>
                    <Form.Item
                      label={t("agentConfig.exemptFileExtensions")}
                      name={[
                        "light_context_config",
                        "tool_result_pruning_config",
                        "exempt_file_extensions",
                      ]}
                      tooltip={t("agentConfig.exemptFileExtensionsTooltip")}
                    >
                      <Select
                        mode="tags"
                        placeholder={t(
                          "agentConfig.exemptFileExtensionsPlaceholder",
                        )}
                        tokenSeparators={[",", " "]}
                        style={{ width: "100%" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.exemptToolNames")}
                      name={[
                        "light_context_config",
                        "tool_result_pruning_config",
                        "exempt_tool_names",
                      ]}
                      tooltip={t("agentConfig.exemptToolNamesTooltip")}
                    >
                      <Select
                        mode="tags"
                        placeholder={t(
                          "agentConfig.exemptToolNamesPlaceholder",
                        )}
                        tokenSeparators={[",", " "]}
                        style={{ width: "100%" }}
                      />
                    </Form.Item>
                  </>
                )}
              </>
            ),
          },
          {
            key: "visualCompression",
            label: t("agentConfig.visualCompressionCollapseLabel"),
            children: (
              <>
                <Form.Item
                  label={t("agentConfig.visualCompressionEnabled")}
                  name={[
                    "light_context_config",
                    "visual_compression_config",
                    "enabled",
                  ]}
                  valuePropName="checked"
                  tooltip={t("agentConfig.visualCompressionEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>

                {SHOW_EXPERIMENTAL_VISUAL_COMPRESSION_TUNING && (
                  <>
                    <Form.Item
                      label={t("agentConfig.visualCompressionModels")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "allowed_models",
                      ]}
                      tooltip={t("agentConfig.visualCompressionModelsTooltip")}
                    >
                      <Select
                        mode="tags"
                        placeholder="qwen3.7-plus"
                        tokenSeparators={[",", " "]}
                        style={{ width: "100%" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionProfile")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "render_profile",
                      ]}
                      tooltip={t("agentConfig.visualCompressionProfileTooltip")}
                    >
                      <Select
                        options={[
                          {
                            value: "calibrated",
                            label: "Calibrated (Spleen 5×8)",
                          },
                          { value: "5x8", label: "5×8" },
                          { value: "7x10", label: "7×10" },
                          { value: "9x12", label: "9×12" },
                        ]}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionMinStaticTokens")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "min_static_tokens",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionMinStaticTokensTooltip",
                      )}
                    >
                      <SliderWithValue min={0} max={4000} step={100} />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionMinChars")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "min_block_chars",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionMinCharsTooltip",
                      )}
                    >
                      <SliderWithValue
                        min={1000}
                        max={20000}
                        step={1000}
                        marks={{ 1000: "1K", 6000: "6K", 20000: "20K" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionRecent")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "keep_recent_messages",
                      ]}
                      tooltip={t("agentConfig.visualCompressionRecentTooltip")}
                    >
                      <SliderWithValue
                        min={1}
                        max={20}
                        step={1}
                        marks={{ 1: "1", 6: "6", 20: "20" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionMaxImages")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "max_images_per_request",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionMaxImagesTooltip",
                      )}
                    >
                      <SliderWithValue
                        min={1}
                        max={100}
                        step={1}
                        marks={{ 1: "1", 32: "32", 100: "100" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionHistoryChunk")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "history_chunk_messages",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionHistoryChunkTooltip",
                      )}
                    >
                      <SliderWithValue min={2} max={50} step={2} />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionMaxToolImages")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "max_images_per_tool_result",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionMaxToolImagesTooltip",
                      )}
                    >
                      <SliderWithValue min={1} max={32} step={1} />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionFactsheetLimit")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "factsheet_limit",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionFactsheetLimitTooltip",
                      )}
                    >
                      <SliderWithValue min={0} max={96} step={8} />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionKeepSharpTools")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "keep_sharp_tool_names",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionKeepSharpToolsTooltip",
                      )}
                    >
                      <Select mode="tags" tokenSeparators={[",", " "]} />
                    </Form.Item>

                    <Form.Item
                      label={t(
                        "agentConfig.visualCompressionKeepSharpPatterns",
                      )}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "keep_sharp_patterns",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionKeepSharpPatternsTooltip",
                      )}
                    >
                      <Select mode="tags" tokenSeparators={[","]} />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionCostRatio")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "max_visual_cost_ratio",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionCostRatioTooltip",
                      )}
                    >
                      <SliderWithValue
                        min={0.5}
                        max={2}
                        step={0.05}
                        marks={{ 0.5: "0.5×", 1: "1×", 1.15: "1.15×", 2: "2×" }}
                      />
                    </Form.Item>

                    <Form.Item
                      label={t("agentConfig.visualCompressionSafetyMargin")}
                      name={[
                        "light_context_config",
                        "visual_compression_config",
                        "image_cost_safety_margin",
                      ]}
                      tooltip={t(
                        "agentConfig.visualCompressionSafetyMarginTooltip",
                      )}
                    >
                      <SliderWithValue
                        min={1}
                        max={2}
                        step={0.05}
                        marks={{ 1: "1×", 1.1: "1.1×", 1.5: "1.5×", 2: "2×" }}
                      />
                    </Form.Item>

                    {[
                      ["compress_system", "visualCompressionSystem"],
                      ["compress_tools", "visualCompressionTools"],
                      ["compress_tool_results", "visualCompressionToolResults"],
                      ["compress_history", "visualCompressionHistory"],
                      ["emit_factsheet", "visualCompressionFactsheet"],
                      ["emit_recoverable", "visualCompressionRecoverable"],
                    ].map(([field, label]) => (
                      <Form.Item
                        key={field}
                        label={t(`agentConfig.${label}`)}
                        name={[
                          "light_context_config",
                          "visual_compression_config",
                          field,
                        ]}
                        valuePropName="checked"
                      >
                        <Switch />
                      </Form.Item>
                    ))}
                  </>
                )}
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
