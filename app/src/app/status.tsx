import { Stack } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";

import { API_URL, fetchHealth, type Health } from "@/services/api";

type HealthState =
  | { kind: "loading" }
  | { kind: "loaded"; health: Health }
  | { kind: "failed"; message: string };

export default function HealthScreen() {
  const [state, setState] = useState<HealthState>({ kind: "loading" });

  const load = useCallback(
    () =>
      fetchHealth().then(
        (health) => setState({ kind: "loaded", health }),
        (error: unknown) =>
          setState({
            kind: "failed",
            message: error instanceof Error ? error.message : String(error),
          }),
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
    <View style={styles.container}>
      <Stack.Screen options={{ title: "Server status" }} />
      <Text style={styles.title}>Server status</Text>
      <Text style={styles.muted}>{API_URL}</Text>

      {state.kind === "loading" && (
        <>
          <ActivityIndicator size="large" />
          <Text style={styles.muted}>The free server may need up to a minute to wake up.</Text>
        </>
      )}

      {state.kind === "loaded" && (
        <>
          <Text style={styles.text}>API: {state.health.status}</Text>
          <Text style={styles.text}>Database: {state.health.database}</Text>
          <Text style={styles.muted}>Version: {state.health.version}</Text>
        </>
      )}

      {state.kind === "failed" && <Text style={styles.error}>{state.message}</Text>}

      <Pressable style={styles.button} onPress={retry} disabled={state.kind === "loading"}>
        <Text style={styles.buttonText}>Check again</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: 24,
    backgroundColor: "#ffffff",
  },
  title: { fontSize: 24, fontWeight: "600", color: "#111111" },
  text: { fontSize: 18, color: "#111111" },
  muted: { fontSize: 14, color: "#666666", textAlign: "center" },
  error: { fontSize: 16, color: "#b00020", textAlign: "center" },
  button: {
    marginTop: 12,
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    backgroundColor: "#111111",
  },
  buttonText: { color: "#ffffff", fontSize: 16 },
});
