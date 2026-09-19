import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArgHelp } from "@/components/models/ArgHelp";
import { EMPTY_ROW, type SettingRow } from "@/lib/instanceSettings";

const WORDING = {
  arg: { placeholder: "Argument Name", add: "Add Argument" },
  env: { placeholder: "Variable Name", add: "Add Environment Variable" },
} as const;

/**
 * The CLI arguments or the environment variables of an instance as
 * editable rows, for the launch wizard and the Edit settings dialog.
 *
 * An engine default keeps its name (only its value changes); a row the
 * user added can be renamed and deleted. The placeholders and button
 * names are what the page objects find the rows by: keep them.
 */
export function SettingRows({
  kind,
  rows,
  onChange,
  engineName,
}: {
  kind: "arg" | "env";
  rows: SettingRow[];
  onChange: (rows: SettingRow[]) => void;
  engineName?: string;
}) {
  const wording = WORDING[kind];
  const edit = (index: number, field: "name" | "value", value: string) =>
    onChange(
      rows.map((row, i) =>
        i === index ? { ...row, [field]: value, updated: true } : row
      )
    );
  return (
    <>
      {rows.map((row, index) => (
        <div key={index} className="mb-4 flex space-x-2">
          <Input
            value={row.name}
            readOnly={!row.editable || !row.new}
            onChange={(e) => edit(index, "name", e.target.value)}
            placeholder={wording.placeholder}
            required
          />
          <Input
            value={row.value}
            onChange={(e) => edit(index, "value", e.target.value)}
            placeholder="Value"
            readOnly={!row.editable}
          />
          <ArgHelp engineName={engineName} kind={kind} name={row.name} />
          {row.new && (
            <Button
              type="button"
              variant="destructive"
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
            >
              Delete
            </Button>
          )}
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        onClick={() => onChange([...rows, { ...EMPTY_ROW }])}
      >
        {wording.add}
      </Button>
    </>
  );
}
