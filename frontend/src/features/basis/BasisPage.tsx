import { useSearchParams } from 'react-router-dom';
import { Tabs } from '../../components/Tabs';
import { PageHead } from '../../components/ui';
import { FactsPanel } from '../facts/FactsPanel';
import { RulesPanel } from '../rules/RulesPanel';

/**
 * 依据：评审所依据的规则与事实。规则确认可以晚一点，未确认也照常评审（报告里标明“依据未确认”）；
 * 只有废标／否决／强制类规则必须在登记提交前确认。
 */
export function BasisPage() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get('tab') === 'facts' ? 'facts' : 'rules';
  return (
    <>
      <PageHead
        title="依据"
        lede="评审依据的招标规则与人工录入的事实。规则未确认也照常评审，但废标／否决／强制类规则须在登记提交前确认。"
      />
      <Tabs
        label="依据"
        active={tab}
        onChange={(id) => {
          setSp(id === 'facts' ? { tab: 'facts' } : {}, { replace: true });
        }}
        tabs={[
          { id: 'rules', label: '规则', panel: <RulesPanel /> },
          { id: 'facts', label: '事实库', panel: <FactsPanel /> },
        ]}
      />
    </>
  );
}
