import { useState } from "react";
import { createRoot } from "react-dom/client";
import "../../src/styles.css";
import { SubmissionPanel } from "../../src/SubmissionPanel";
import { ReportPanel } from "../../src/ReportPanel";
import { PricingPanel } from "../../src/PricingPanel";
function Fixture() {
  const [page, setPage] = useState("submission");
  return (
    <div className="page-content project-page">
      <p className="notice warning">
        客户端机制夹具：全部业务响应由测试提供，没有连接实际业务API，不代表真实业务验收。
      </p>
      <nav className="review-shortcuts" aria-label="测试页面">
        <button onClick={() => setPage("submission")}>提交机制</button>
        <button onClick={() => setPage("report")}>报告机制</button>
        <button onClick={() => setPage("pricing")}>报价机制</button>
      </nav>
      {page === "submission" ? (
        <SubmissionPanel
          bidId="bid"
          memberId="mechanism-member"
          onNavigate={() => {}}
          onChanged={() => {}}
        />
      ) : page === "report" ? (
        <ReportPanel
          bidId="bid"
          memberId="mechanism-member"
          reviewId="review"
          projectTitle="合成客户端机制项目"
        />
      ) : (
        <PricingPanel
          bidId="bid"
          memberId="mechanism-member"
          onSettings={() => {}}
        />
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
