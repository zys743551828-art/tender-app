import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { RuleSet, TermAlternative, TermConflict } from '../../api/types';
import { Button } from '../../components/ui/button';
import { Dialog, DialogActions } from '../../components/Dialog';
import { ErrorNotice, Field } from '../../components/ui';
import { Textarea } from '../../components/ui/input';
import { useResolveTerm } from './actions';

const titles = { technical_full_score: '技术标满分', price_rule: '评标价规则' };

export function TermConflicts({ projectId, set }: { projectId: string; set: RuleSet }) {
  const [choice, setChoice] = useState<{
    term: TermConflict['term'];
    option: TermAlternative;
    revision: number;
  } | null>(null);
  return (
    <>
      {(set.terms.conflicts ?? []).map((conflict) => (
        <section key={conflict.term} className="mb-5 rounded-lg border border-danger p-4">
          <h3 className="text-sm font-semibold">
            {titles[conflict.term]}存在不同要求，请核实采用哪一项
          </h3>
          <p className="text-muted-foreground">
            这些原文给出的条件不同，新的评审暂不采用任何一项。请核对补遗的适用范围和生效说明；不能仅按上传先后决定。
          </p>
          {conflict.alternatives.map((option) => (
            <div key={option.option_id} className="mt-3 border-t border-border pt-3">
              <blockquote className="m-0 whitespace-pre-wrap text-sm">{option.quote}</blockquote>
              <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
                {option.evidence.map((e) => (
                  <Link
                    key={e.evidence_id}
                    to={`/projects/${projectId}/evidence/${e.evidence_id}`}
                    className="text-primary underline"
                  >
                    {e.file_name} · 第 {e.physical_page} 页
                  </Link>
                ))}
                <Button
                  size="sm"
                  onClick={() => {
                    setChoice({ term: conflict.term, option, revision: set.revision });
                  }}
                >
                  采用此项
                </Button>
              </div>
            </div>
          ))}
        </section>
      ))}
      {choice ? (
        <ResolveDialog
          projectId={projectId}
          revision={choice.revision}
          term={choice.term}
          option={choice.option}
          onClose={() => {
            setChoice(null);
          }}
        />
      ) : null}
    </>
  );
}

function ResolveDialog({
  projectId,
  revision,
  term,
  option,
  onClose,
}: {
  projectId: string;
  revision: number;
  term: TermConflict['term'];
  option: TermAlternative;
  onClose: () => void;
}) {
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const action = useResolveTerm(projectId, onClose);
  return (
    <Dialog title={`核实${titles[term]}`} onClose={onClose}>
      <blockquote className="m-0 mb-3 text-sm">{option.quote}</blockquote>
      <p className="text-muted-foreground">
        确认后创建新规则版本，重新评审后生效。已有报告保持原来的依据。此处只选择该投标条件，其他规则仍需逐条核对。
      </p>
      <Field
        label="采用依据"
        error={
          touched && !reason.trim()
            ? '请说明该项为何适用于当前投标，例如补遗明确替代了哪条要求'
            : null
        }
      >
        {(props) => (
          <Textarea
            {...props}
            value={reason}
            rows={3}
            data-autofocus
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        )}
      </Field>
      {action.isError ? (
        <ErrorNotice error={action.error} title="没有保存，请刷新后核实当前规则版本" />
      ) : null}
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button
          variant="primary"
          disabled={action.isPending}
          onClick={() => {
            setTouched(true);
            if (reason.trim())
              action.mutate({
                object_version: String(revision),
                term,
                option_id: option.option_id,
                reason: reason.trim(),
              });
          }}
        >
          确认采用此项
        </Button>
      </DialogActions>
    </Dialog>
  );
}
