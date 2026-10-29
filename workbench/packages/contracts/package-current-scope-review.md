# 当前材料与独立审核的联合观察

`package_current_scope_review.py` 只组合已实现的受控读取端口，不开写接口、不接受调用者自报回执或资格。必须提供准确私有 recovery、登记命令、主体命令的commit摘要，独立固定context／登记记录／主体记录摘要，及准确bid／scope／scope摘要。范围、原件、解析、登记、主体核验采用五个独立且空闲的连接；不切角色、不创建连接／配置／权限，不读官方标签或业务env。

流程：重读两个私有命令并固定项目／范围→恢复准确旧context并新取当前全部原件及原生来源→从原context重建完整范围清单→按主体命令所指固定commit重读、复验完整私有报告→独立读取原生材料登记并比对命令及context→独立读取原生主体声明和当前配置→再次恢复当前材料／来源→再次读取主体配置。报告、清单、登记、主体case与准确context必须全部匹配，报告不能从另一个版本或“最新”结果补取。

旧登记中 recovery_observation_digest 保持原登记引用，不冒充本次新恢复观察；旧context的来源观察、input_as_of和摘要不变。初次／最后恢复回执及主体观察单独保存，主体不可变记录两次相同，当前profile／case须均有效，除观察时间外当前head及状态也须保持；撤销后重启用但版本变化仍拒绝。来源关闭／撤回／替换、报告损坏、原生记录或命令错配均不交付结果。所有外部GET发生在受控事务之外。

返回 `CurrentScopeReview(context, metadata)`，保存上述固定摘要与四份新观察，不复制私有正文或定位。`status` 区分 `review_changes_required`、`review_incomplete`、`synthetic_review_only`、`configured_review_confirmed`。全部完整声明在synthetic_mechanism模式仍不能当真实审核；current_prebid配置且全部事项声明确认，只置 `configured_current_review_confirmed`，描述已配置主体所作声明的接受情况，不证明实际人工阅读或内容真值。

`current_native_material_rechecked` 和 `configured_issuer_identity_verified` 是本次分阶段读取事实。分阶段读取不构成原子联合快照、租约或执行屏障，`atomic_snapshot_verified`／`send_lease_granted` 固定false。`actual_human_reading_verified`、`trusted_derivation_bound`、`necessary_scope_verified`、`native_binding_verified`、`input_authority_granted`、`execution_authorized`、`historical_existence_verified` 也固定false；真实受限渲染已另有联合流程，但尚须把其受信回执与这份准确持久context接入原生正向登记。

来源仍可能在最后一个读取之后变化，发送时须由后续原生锁／generation／fence重新核验，不得复用本观察当永久资格。当前模式的测试配置只在独立合成库创建，不证明真实人员审核，也不安装生产配置。方法摘要固定组合源码及所有依赖方法，旧方法和记录不改。公开HTTP／UI／费用／Worker仍独立实施。
