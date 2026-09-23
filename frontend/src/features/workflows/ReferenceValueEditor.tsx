import type { WorkflowReferenceValue } from "../../api/types";
import {
  referencePipe,
  setReferencePath,
  setReferencePipe,
  type ReferenceGroup,
} from "./graphModel";
import ReferencePicker from "./ReferencePicker";
import PipeEditor from "./PipeEditor";

export interface ReferenceValueEditorProps {
  idPrefix: string;
  groups: ReferenceGroup[];
  value: WorkflowReferenceValue;
  onChange: (value: WorkflowReferenceValue) => void;
}

/** Reference picker plus its value pipeline, shared by both value editors. */
export default function ReferenceValueEditor({
  idPrefix,
  groups,
  value,
  onChange,
}: ReferenceValueEditorProps) {
  return (
    <>
      <ReferencePicker
        idPrefix={idPrefix}
        groups={groups}
        value={value.$ref}
        onChange={(path) => onChange(setReferencePath(value, path))}
      />
      <PipeEditor
        idPrefix={idPrefix}
        pipe={referencePipe(value)}
        onChange={(pipe) => onChange(setReferencePipe(value, pipe))}
      />
    </>
  );
}
