import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import {
  Card,
  Chip,
  ConfirmSheet,
  HeroCard,
  LargeTitle,
  Loading,
  Notice,
  PillButton,
  Screen,
  SectionTitle,
} from "@/components/ui";
import {
  confirmMandate,
  errorMessage,
  fetchMandates,
  revokeMandate,
  tightenMandate,
  type Mandate,
  type MandateTightening,
} from "@/services/api";
import { describeRule, purchaseLimitChf, UNCERTAINTY_DESCRIPTIONS } from "@/services/policy";
import { colors, formatChf, radius, spacing, type } from "@/theme";

type ScreenState =
  | { kind: "loading" }
  | { kind: "loaded"; mandates: Mandate[] }
  | { kind: "failed"; message: string };

type Feedback = { tone: "success" | "danger"; text: string };

export default function PolicyScreen() {
  const [state, setState] = useState<ScreenState>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [confirmingRevoke, setConfirmingRevoke] = useState(false);

  const load = useCallback(
    () =>
      fetchMandates().then(
        (mandates) => setState({ kind: "loaded", mandates }),
        (error: unknown) => setState({ kind: "failed", message: errorMessage(error) }),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  /** Runs one mandate action, swaps in the server's updated mandate, reports the outcome. */
  const act = async (action: () => Promise<Mandate>, success: string) => {
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await action();
      setState((previous) =>
        previous.kind === "loaded"
          ? {
              ...previous,
              mandates: previous.mandates.map((m) => (m.id === updated.id ? updated : m)),
            }
          : previous,
      );
      setFeedback({ tone: "success", text: success });
    } catch (error) {
      setFeedback({ tone: "danger", text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  if (state.kind === "loading") {
    return (
      <Screen>
        <LargeTitle>Wallet policy</LargeTitle>
        <Loading />
      </Screen>
    );
  }

  if (state.kind === "failed") {
    return (
      <Screen>
        <LargeTitle>Wallet policy</LargeTitle>
        <Card>
          <Text style={type.body}>Could not load your policy.</Text>
          <Text style={type.small}>{state.message}</Text>
          <PillButton
            label="Try again"
            variant="secondary"
            onPress={() => {
              setState({ kind: "loading" });
              load();
            }}
          />
        </Card>
      </Screen>
    );
  }

  if (state.mandates.length === 0) {
    return (
      <Screen>
        <LargeTitle>Wallet policy</LargeTitle>
        <Card>
          <Text style={type.body}>No wallet policy yet.</Text>
        </Card>
      </Screen>
    );
  }

  // Most recent first (server ordering); default to the newest one.
  const mandate = state.mandates.find((m) => m.id === selectedId) ?? state.mandates[0];
  const others = state.mandates.filter((m) => m.id !== mandate.id);
  const limit = purchaseLimitChf(mandate.hard_rules);

  return (
    <Screen>
      <LargeTitle>Wallet policy</LargeTitle>

      <HeroCard>
        <View style={styles.heroTop}>
          <Text style={styles.heroLabel}>Limit per purchase</Text>
          <StatusChip status={mandate.status} />
        </View>
        <Text style={styles.heroValue}>{limit !== null ? formatChf(limit) : "No limit"}</Text>
        <Text style={styles.heroDetail}>{UNCERTAINTY_DESCRIPTIONS[mandate.uncertainty_policy]}</Text>
      </HeroCard>

      {feedback && <Notice tone={feedback.tone}>{feedback.text}</Notice>}

      {mandate.status === "draft" && (
        <Card>
          <Text style={type.body}>
            Your agent cannot spend anything until you confirm this policy.
          </Text>
          <PillButton
            label="Confirm policy"
            busy={busy}
            onPress={() =>
              act(() => confirmMandate(mandate.id), "Policy confirmed. Your agent may now shop.")
            }
          />
        </Card>
      )}

      <SectionTitle>In your words</SectionTitle>
      <Card>
        <Text style={styles.quote}>“{mandate.instruction}”</Text>
      </Card>

      <SectionTitle>What the wallet enforces</SectionTitle>
      <Card>
        {mandate.hard_rules.length === 0 ? (
          <Text style={type.secondary}>No fixed rules.</Text>
        ) : (
          mandate.hard_rules.map((rule, index) => (
            <View key={index} style={[styles.rule, index > 0 && styles.ruleDivider]}>
              <Text style={type.body}>{describeRule(rule)}</Text>
            </View>
          ))
        )}
        <Text style={type.small}>
          Checked on every purchase, together with what you asked for and whether the shop and
          item match it.
        </Text>
      </Card>

      {mandate.guidance.length > 0 && (
        <>
          <SectionTitle>How we read your instruction</SectionTitle>
          <Card>
            {mandate.guidance.map((line, index) => (
              <Text key={index} style={type.body}>
                • {line}
              </Text>
            ))}
          </Card>
        </>
      )}

      {mandate.open_questions.length > 0 && (
        <>
          <SectionTitle>Open questions</SectionTitle>
          <Card style={styles.questions}>
            {mandate.open_questions.map((line, index) => (
              <Text key={index} style={type.body}>
                • {line}
              </Text>
            ))}
          </Card>
        </>
      )}

      {mandate.status === "active" && (
        <>
          <SectionTitle>Tighten</SectionTitle>
          <TightenPanel
            mandate={mandate}
            currentLimit={limit}
            busy={busy}
            onTighten={(change, success) => act(() => tightenMandate(mandate.id, change), success)}
          />

          <PillButton
            label="Revoke policy"
            variant="danger"
            disabled={busy}
            onPress={() => setConfirmingRevoke(true)}
          />
          <ConfirmSheet
            visible={confirmingRevoke}
            icon="🔒"
            title="Revoke this policy?"
            message={
              "Your shopping agent will no longer be able to spend with this card. " +
              "Purchases already waiting for you are not approved."
            }
            confirmLabel="Yes, revoke"
            onCancel={() => setConfirmingRevoke(false)}
            onConfirm={() => {
              setConfirmingRevoke(false);
              act(
                () => revokeMandate(mandate.id),
                "Policy revoked. Your agent can no longer spend with this card.",
              );
            }}
          />
        </>
      )}

      {mandate.confirmed_at && (
        <Text style={styles.meta}>
          Confirmed {new Date(mandate.confirmed_at).toLocaleString("de-CH")}
          {mandate.confirmed_by ? ` by ${mandate.confirmed_by}` : ""}
        </Text>
      )}

      {others.length > 0 && (
        <>
          <SectionTitle>Other policies</SectionTitle>
          {others.map((other) => (
            <Pressable
              key={other.id}
              style={({ pressed }) => [styles.other, pressed && styles.pressed]}
              onPress={() => {
                setSelectedId(other.id);
                setFeedback(null);
              }}
            >
              <Text style={[type.body, styles.otherText]} numberOfLines={1}>
                {other.instruction}
              </Text>
              <StatusChip status={other.status} />
            </Pressable>
          ))}
        </>
      )}
    </Screen>
  );
}

function StatusChip({ status }: { status: Mandate["status"] }) {
  const { label, tone } = {
    draft: { label: "Draft", tone: "attention" as const },
    active: { label: "Active", tone: "success" as const },
    revoked: { label: "Revoked", tone: "danger" as const },
  }[status];
  return <Chip label={label} tone={tone} />;
}

/** Tightening only: a lower spending limit, or declining instead of asking when unsure. */
function TightenPanel({
  mandate,
  currentLimit,
  busy,
  onTighten,
}: {
  mandate: Mandate;
  currentLimit: number | null;
  busy: boolean;
  onTighten: (change: MandateTightening, success: string) => void;
}) {
  const [limit, setLimit] = useState("");
  const parsed = Number(limit.replace(",", "."));
  const limitValid = limit.trim() !== "" && Number.isFinite(parsed) && parsed > 0;

  return (
    <Card style={styles.panel}>
      <Text style={type.small}>
        You can always make the policy stricter. Loosening it needs a new policy.
      </Text>

      <Text style={type.body}>New limit per purchase</Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={limit}
          onChangeText={setLimit}
          keyboardType="decimal-pad"
          placeholder={currentLimit !== null ? `below ${currentLimit.toFixed(0)}` : "CHF"}
          placeholderTextColor={colors.textMuted}
        />
        <PillButton
          label="Apply"
          disabled={!limitValid}
          busy={busy}
          onPress={() => {
            onTighten(
              {
                // Existing rules are resent unchanged; the new one is added on top.
                hard_rules: [
                  ...mandate.hard_rules,
                  {
                    field: "authorization.billing_amount_chf",
                    operator: "<=",
                    value: parsed,
                    currency: "CHF",
                    scope: "purchase",
                  },
                ],
              },
              `Limit set to ${formatChf(parsed)} per purchase.`,
            );
            setLimit("");
          }}
        />
      </View>
      {limitValid && currentLimit !== null && parsed >= currentLimit && (
        <Text style={type.small}>
          This is not lower than your current limit, so it will not change anything.
        </Text>
      )}

      {mandate.uncertainty_policy !== "decline" && (
        <PillButton
          label="Decline instead of asking when unsure"
          variant="secondary"
          disabled={busy}
          onPress={() =>
            onTighten(
              { uncertainty_policy: "decline" },
              "From now on, unsure purchases are declined instead.",
            )
          }
        />
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  heroTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  heroLabel: { fontSize: 20, fontWeight: "500", color: colors.onHero },
  heroValue: { fontSize: 40, fontWeight: "600", color: colors.onHero },
  heroDetail: { fontSize: 17, color: colors.onHeroMuted },
  quote: { fontSize: 19, fontStyle: "italic", color: colors.text, lineHeight: 27 },
  rule: { paddingVertical: spacing.sm },
  ruleDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  questions: { backgroundColor: colors.attentionSurface },
  panel: { gap: spacing.md },
  row: { flexDirection: "row", gap: spacing.sm, alignItems: "center" },
  input: {
    flex: 1,
    minHeight: 52,
    backgroundColor: colors.surfaceRaised,
    borderRadius: radius.chip,
    paddingHorizontal: spacing.lg,
    fontSize: 18,
    color: colors.text,
  },
  meta: { ...type.small, textAlign: "center" },
  other: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    padding: spacing.lg,
  },
  otherText: { flex: 1 },
  pressed: { opacity: 0.75 },
});
