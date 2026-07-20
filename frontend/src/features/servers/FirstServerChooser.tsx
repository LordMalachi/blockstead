export type FirstServerPath = "create" | "import" | "modpack";

const choices: Array<{
  value: FirstServerPath;
  title: string;
  detail: string;
  recommended?: boolean;
}> = [
  {
    value: "create",
    title: "Create a new server",
    detail: "Blockstead downloads and configures the server for you.",
    recommended: true,
  },
  {
    value: "import",
    title: "Use an existing server",
    detail: "Copy an existing Minecraft server folder into Blockstead.",
  },
  {
    value: "modpack",
    title: "Start with a modpack",
    detail: "Find a Modrinth pack or import a local .mrpack file.",
  },
];

export function FirstServerChooser({
  value,
  onChange,
}: {
  value: FirstServerPath;
  onChange: (value: FirstServerPath) => void;
}) {
  return <section className="card first-server-guide" aria-labelledby="first-server-title">
    <p className="eyebrow">First server</p>
    <h2 id="first-server-title">How would you like to begin?</h2>
    <p>Choose one setup path. You can add other kinds of servers later.</p>
    <div className="first-server-choices" role="group" aria-label="First server setup method">
      {choices.map(choice => <button
        key={choice.value}
        type="button"
        className={`first-server-choice${value === choice.value ? " first-server-choice--active" : ""}`}
        aria-pressed={value === choice.value}
        onClick={() => onChange(choice.value)}
      >
        <span>
          <strong>{choice.title}</strong>
          {choice.recommended && <small>Recommended</small>}
        </span>
        <em>{choice.detail}</em>
      </button>)}
    </div>
  </section>;
}
