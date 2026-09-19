import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { BackLink, Card, Chip, LargeTitle, Loading, PillButton, Screen } from "@/components/ui";
import { API_URL, errorMessage, fetchHealth, type Health } from "@/services/api";
import { type } from "@/theme";

type HealthState =
  | { kind: "loading" }
  | { kind: "loaded"; health: Health }
  | { kind: "failed"; message: string };

export default function HealthScreen() {
  const router = useRouter();
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  const load = useCallback(
    () =>
      fetchHealth().then(
        (health) => setState({ kind: "loaded", health }),
        (error: unknown) => setState({ kind: "failed", message: errorMessage(error) }),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  const retry = () => {
    setState({ kind: "loading" });
    load();
  };

  return (
    <Screen>
      {/* Opened on top of the tabs; a deep link on web has nothing to go back to. */}
      <BackLink onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} />
      <LargeTitle>Server status</LargeTitle>
      <Text style={type.small}>{API_URL}</Text>

      {state.kind === "loading" && (
        <>
          <Loading />
          <Text style={[type.secondary, styles.center]}>
            The free server may need up to a minute to wake up.
          </Text>
        </>
      )}

      {state.kind === "loaded" && (
        <Card>
          <Row label="API" ok={state.health.status === "ok"} />
          <Row label="Database" ok={state.health.database === "ok"} />
          <Text style={type.small}>Version: {state.health.version}</Text>
        </Card>
      )}

      {state.kind === "failed" && (
        <Card>
          <Text style={type.body}>The server could not be reached.</Text>
          <Text style={type.small}>{state.message}</Text>
        </Card>
      )}

      <PillButton
        label="Check again"
        variant="secondary"
        disabled={state.kind === "loading"}
        onPress={retry}
      />
    </Screen>
  );
}

function Row({ label, ok }: { label: string; ok: boolean }) {
  return (
    <View style={styles.row}>
      <Text style={type.body}>{label}</Text>
      <Chip label={ok ? "OK" : "Error"} tone={ok ? "success" : "danger"} />
    </View>
  );
}

const styles = StyleSheet.create({
  center: { textAlign: "center" },
  row: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
});
