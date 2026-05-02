export default async function ObsPage({ params, searchParams }: { params: Promise<{ sessionId: string }>; searchParams: Promise<{ token?: string }> }) {
  const { sessionId } = await params;
  const { token } = await searchParams;
  return (
    <main style={{ margin: 0, background: "black" }}>
      <p style={{ color: "#ddd", margin: 8 }}>OBS Source: {sessionId} token={token ? "ok" : "missing"}</p>
      <video autoPlay muted playsInline style={{ width: "100vw", height: "100vh", objectFit: "cover" }} />
    </main>
  );
}
