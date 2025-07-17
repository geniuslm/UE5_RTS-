# UE5 RTS网络架构设计方案
## Claude专项设计方案

> **专项目标**：轻量级权威服务器 + P2P分摊的网络架构  
> **技术重点**：Mass数据同步、服务器仲裁、P2P通信、网络优化  
> **支持规模**：12人大战、800+单位同屏、延迟<100ms  

---

## 一、网络架构总览

### 1.1 混合网络模型

#### 角色分工设计
```
┌─────────────────────────────────────────────┐
│               轻量级权威服务器                │
│  ┌─────────────────────────────────────────┐ │
│  │ 仲裁服务 (Authority Services)          │ │
│  │ • 伤害计算验证                         │ │
│  │ • 技能使用验证                         │ │
│  │ • 关键状态仲裁                         │ │
│  │ • 反作弊检测                           │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
                        ↕
┌─────────────────────────────────────────────┐
│                P2P客户端网络                │
│  ┌─────────────────────────────────────────┐ │
│  │ 计算分摊服务 (Compute Services)        │ │
│  │ • 移动计算和同步                       │ │
│  │ • AI决策执行                           │ │
│  │ • 渲染和表现                           │ │
│  │ • 非关键状态同步                       │ │
│  └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

#### 数据流向设计
```
客户端输入 → P2P广播 → 所有客户端执行 → 关键结果 → 服务器验证 → 结果确认 → P2P广播
     ↓
本地预测执行 (降低延迟感知)
```

### 1.2 Mass数据同步策略

#### Fragment同步分类
```cpp
// 同步优先级枚举
enum class EFragmentSyncPriority : uint8
{
    Critical,     // 关键数据，高频同步，服务器权威
    Important,    // 重要数据，中频同步，P2P同步
    Normal,       // 一般数据，低频同步，P2P同步
    Local,        // 本地数据，不同步
    Predicted     // 预测数据，客户端预测+服务器校正
};

// Fragment同步配置
struct FFragmentSyncConfig
{
    EFragmentSyncPriority Priority;
    float SyncFrequency;        // 同步频率（Hz）
    bool bRequireReliable;      // 是否需要可靠传输
    bool bCompressData;         // 是否压缩数据
    bool bDeltaCompress;        // 是否使用差分压缩
};

// 同步配置映射
TMap<UScriptStruct*, FFragmentSyncConfig> FragmentSyncConfigs = {
    {FHealthFragment::StaticStruct(), {EFragmentSyncPriority::Critical, 10.0f, true, true, true}},
    {FTransformFragment::StaticStruct(), {EFragmentSyncPriority::Predicted, 20.0f, false, true, true}},
    {FAttackFragment::StaticStruct(), {EFragmentSyncPriority::Important, 5.0f, true, true, false}},
    {FMovementFragment::StaticStruct(), {EFragmentSyncPriority::Predicted, 20.0f, false, true, true}},
    {FRenderFragment::StaticStruct(), {EFragmentSyncPriority::Local, 0.0f, false, false, false}},
    {FEffectFragment::StaticStruct(), {EFragmentSyncPriority::Normal, 2.0f, false, true, false}}
};
```

---

## 二、服务器仲裁系统

### 2.1 权威服务器架构

#### 核心仲裁处理器
```cpp
// 权威伤害处理器
UCLASS()
class UAuthorityDamageProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UAuthorityDamageProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery AuthorityDamageQuery;
    
    // 权威验证
    bool ValidateDamageRequest(const FDamageRequestFragment& Request, const FMassEntityManager& EntityManager);
    float CalculateAuthorityDamage(const FDamageRequestFragment& Request, const FDefenseFragment& Defense, const FMassEntityManager& EntityManager);
    void BroadcastDamageResult(const FDamageResultFragment& Result, const FMassEntityManager& EntityManager);
    
    // 反作弊检测
    bool DetectDamageCheat(const FDamageRequestFragment& Request, const FMassEntityManager& EntityManager);
    void LogSuspiciousActivity(const FString& Reason, const FDamageRequestFragment& Request);
};

// 权威伤害结果Fragment
USTRUCT()
struct FDamageResultFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(Replicated)
    FMassEntityHandle TargetEntity;
    
    UPROPERTY(Replicated)
    FMassEntityHandle AttackerEntity;
    
    UPROPERTY(Replicated)
    float AuthorityDamage;      // 服务器计算的最终伤害
    
    UPROPERTY(Replicated)
    float ResultingHealth;      // 伤害后的生命值
    
    UPROPERTY(Replicated)
    uint32 DamageSequence;      // 伤害序列号，用于去重
    
    UPROPERTY(Replicated)
    float ServerTimestamp;      // 服务器时间戳
    
    bool bIsAuthoritative = true;
};

bool UAuthorityDamageProcessor::ValidateDamageRequest(const FDamageRequestFragment& Request, const FMassEntityManager& EntityManager)
{
    // 1. 验证攻击者存在性
    FMassEntityView AttackerView(EntityManager, Request.AttackerEntity);
    if (!AttackerView.IsSet())
    {
        LogSuspiciousActivity("Invalid attacker entity", Request);
        return false;
    }
    
    // 2. 验证目标存在性
    FMassEntityView TargetView(EntityManager, Request.TargetEntity);
    if (!TargetView.IsSet())
    {
        return false;  // 目标可能已死亡，不算作弊
    }
    
    // 3. 验证攻击距离
    const FTransformFragment& AttackerTransform = AttackerView.GetFragmentData<FTransformFragment>();
    const FTransformFragment& TargetTransform = TargetView.GetFragmentData<FTransformFragment>();
    const FAttackFragment& AttackFragment = AttackerView.GetFragmentData<FAttackFragment>();
    
    float Distance = FVector::Dist(AttackerTransform.Position, TargetTransform.Position);
    if (Distance > AttackFragment.AttackRange * 1.1f)  // 10%容错
    {
        LogSuspiciousActivity("Attack range exceeded", Request);
        return false;
    }
    
    // 4. 验证攻击冷却
    float CurrentTime = EntityManager.GetWorld().GetTimeSeconds();
    if (CurrentTime - AttackFragment.LastAttackTime < (1.0f / AttackFragment.AttackSpeed) * 0.9f)  // 10%容错
    {
        LogSuspiciousActivity("Attack cooldown violation", Request);
        return false;
    }
    
    // 5. 验证伤害数值合理性
    if (Request.DamageAmount > AttackFragment.AttackDamage * 1.5f)  // 50%容错（考虑buff）
    {
        LogSuspiciousActivity("Damage amount suspicious", Request);
        return false;
    }
    
    return true;
}

float UAuthorityDamageProcessor::CalculateAuthorityDamage(const FDamageRequestFragment& Request, const FDefenseFragment& Defense, const FMassEntityManager& EntityManager)
{
    // 使用服务器端的权威数据重新计算伤害
    FMassEntityView AttackerView(EntityManager, Request.AttackerEntity);
    if (!AttackerView.IsSet())
    {
        return 0.0f;
    }
    
    const FAttackFragment& AttackFragment = AttackerView.GetFragmentData<FAttackFragment>();
    
    // 获取攻击者的所有buff和装备加成
    float BaseDamage = AttackFragment.AttackDamage;
    
    // TODO: 添加buff系统的伤害加成计算
    // if (AttackerView.HasFragment<FBuffFragment>())
    // {
    //     BaseDamage *= GetBuffDamageMultiplier(AttackerView.GetFragmentData<FBuffFragment>());
    // }
    
    // 计算防御减免
    float FinalDamage = BaseDamage;
    
    switch (Request.DamageType)
    {
        case 0: // 物理伤害
            FinalDamage *= (1.0f - Defense.DamageReduction);
            FinalDamage = FMath::Max(1.0f, FinalDamage - Defense.Armor);
            break;
        case 1: // 魔法伤害
            FinalDamage *= (1.0f - Defense.MagicResistance);
            break;
        case 2: // 真实伤害
            // 无视防御
            break;
    }
    
    return FinalDamage;
}

void UAuthorityDamageProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    // 只在服务器上执行
    if (!Context.GetWorld()->IsServer())
    {
        return;
    }
    
    AuthorityDamageQuery.ForEachEntityChunk(EntityManager, Context, [this, &EntityManager](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TConstArrayView<FDamageRequestFragment> DamageRequests = Context.GetFragmentView<FDamageRequestFragment>();
        TArrayView<FHealthFragment> Healths = Context.GetMutableFragmentView<FHealthFragment>();
        TConstArrayView<FDefenseFragment> Defenses = Context.GetFragmentView<FDefenseFragment>();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            const FDamageRequestFragment& Request = DamageRequests[EntityIndex];
            FHealthFragment& Health = Healths[EntityIndex];
            const FDefenseFragment& Defense = Defenses[EntityIndex];
            FMassEntityHandle ThisEntity = Entities[EntityIndex];

            // 1. 验证伤害请求
            if (!ValidateDamageRequest(Request, EntityManager))
            {
                Context.Defer().RemoveFragment<FDamageRequestFragment>(ThisEntity);
                continue;
            }

            // 2. 计算权威伤害
            float AuthorityDamage = CalculateAuthorityDamage(Request, Defense, EntityManager);

            // 3. 应用伤害
            float OldHealth = Health.CurrentHealth;
            Health.CurrentHealth = FMath::Max(0.0f, Health.CurrentHealth - AuthorityDamage);

            // 4. 创建权威结果
            FDamageResultFragment Result;
            Result.TargetEntity = ThisEntity;
            Result.AttackerEntity = Request.AttackerEntity;
            Result.AuthorityDamage = AuthorityDamage;
            Result.ResultingHealth = Health.CurrentHealth;
            Result.DamageSequence = GetNextDamageSequence();
            Result.ServerTimestamp = Context.GetWorld()->GetTimeSeconds();

            // 5. 广播结果给所有客户端
            BroadcastDamageResult(Result, EntityManager);

            // 6. 检查死亡
            if (Health.CurrentHealth <= 0.0f && Health.bIsAlive)
            {
                Health.bIsAlive = false;
                
                // 发送权威死亡信号
                if (UMassSignalSubsystem* SignalSubsystem = EntityManager.GetWorld().GetSubsystem<UMassSignalSubsystem>())
                {
                    SignalSubsystem->SignalEntity(TEXT("OnAuthorityEntityDeath"), ThisEntity);
                }
            }

            // 7. 清理请求
            Context.Defer().RemoveFragment<FDamageRequestFragment>(ThisEntity);
        }
    });
}
```

### 2.2 技能系统权威验证

#### 权威技能处理器
```cpp
// 技能使用请求Fragment
USTRUCT()
struct FAbilityRequestFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FMassEntityHandle CasterEntity;
    uint32 AbilityId;
    FVector TargetLocation;
    FMassEntityHandle TargetEntity;
    float ClientTimestamp;
    uint32 RequestSequence;
};

// 权威技能结果Fragment
USTRUCT()
struct FAbilityResultFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(Replicated)
    FMassEntityHandle CasterEntity;
    
    UPROPERTY(Replicated)
    uint32 AbilityId;
    
    UPROPERTY(Replicated)
    bool bWasSuccessful;
    
    UPROPERTY(Replicated)
    FVector AuthorityTargetLocation;
    
    UPROPERTY(Replicated)
    FMassEntityHandle AuthorityTargetEntity;
    
    UPROPERTY(Replicated)
    float ServerTimestamp;
    
    UPROPERTY(Replicated)
    uint32 RequestSequence;
    
    UPROPERTY(Replicated)
    FString FailureReason;  // 失败原因（调试用）
};

UCLASS()
class UAuthorityAbilityProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UAuthorityAbilityProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery AbilityRequestQuery;
    
    // 技能验证
    bool ValidateAbilityRequest(const FAbilityRequestFragment& Request, const FMassEntityManager& EntityManager, FString& OutFailureReason);
    void ExecuteAbilityEffects(const FAbilityRequestFragment& Request, FMassEntityManager& EntityManager);
    void BroadcastAbilityResult(const FAbilityResultFragment& Result, const FMassEntityManager& EntityManager);
    
    // 技能数据
    struct FAbilityData
    {
        float ManaCost;
        float Cooldown;
        float CastTime;
        float Range;
        bool bRequiresTarget;
        bool bRequiresLineOfSight;
    };
    
    TMap<uint32, FAbilityData> AbilityDatabase;
    
    // 冷却跟踪
    TMap<TPair<FMassEntityHandle, uint32>, float> AbilityCooldowns;
};

bool UAuthorityAbilityProcessor::ValidateAbilityRequest(const FAbilityRequestFragment& Request, const FMassEntityManager& EntityManager, FString& OutFailureReason)
{
    // 1. 验证施法者存在性
    FMassEntityView CasterView(EntityManager, Request.CasterEntity);
    if (!CasterView.IsSet())
    {
        OutFailureReason = "Invalid caster entity";
        return false;
    }
    
    // 2. 验证技能存在性
    FAbilityData* AbilityData = AbilityDatabase.Find(Request.AbilityId);
    if (!AbilityData)
    {
        OutFailureReason = "Invalid ability ID";
        return false;
    }
    
    // 3. 验证法力值
    if (CasterView.HasFragment<FManaFragment>())
    {
        const FManaFragment& Mana = CasterView.GetFragmentData<FManaFragment>();
        if (Mana.CurrentMana < AbilityData->ManaCost)
        {
            OutFailureReason = "Insufficient mana";
            return false;
        }
    }
    
    // 4. 验证冷却
    TPair<FMassEntityHandle, uint32> CooldownKey(Request.CasterEntity, Request.AbilityId);
    if (float* LastUseTime = AbilityCooldowns.Find(CooldownKey))
    {
        float CurrentTime = EntityManager.GetWorld().GetTimeSeconds();
        if (CurrentTime - *LastUseTime < AbilityData->Cooldown)
        {
            OutFailureReason = "Ability on cooldown";
            return false;
        }
    }
    
    // 5. 验证施法距离
    if (Request.TargetEntity.IsValid())
    {
        FMassEntityView TargetView(EntityManager, Request.TargetEntity);
        if (TargetView.IsSet())
        {
            const FTransformFragment& CasterTransform = CasterView.GetFragmentData<FTransformFragment>();
            const FTransformFragment& TargetTransform = TargetView.GetFragmentData<FTransformFragment>();
            
            float Distance = FVector::Dist(CasterTransform.Position, TargetTransform.Position);
            if (Distance > AbilityData->Range * 1.1f)  // 10%容错
            {
                OutFailureReason = "Target out of range";
                return false;
            }
        }
    }
    
    // 6. 验证视线（如果需要）
    if (AbilityData->bRequiresLineOfSight)
    {
        // TODO: 实现视线检查
    }
    
    return true;
}

void UAuthorityAbilityProcessor::ExecuteAbilityEffects(const FAbilityRequestFragment& Request, FMassEntityManager& EntityManager)
{
    // 根据技能ID执行不同的效果
    switch (Request.AbilityId)
    {
        case 1: // 火球术
        {
            // 创建火球投射物
            FMassEntityHandle Projectile = CreateProjectile(EntityManager, Request.CasterEntity, Request.TargetLocation, 1);
            break;
        }
        case 2: // 治疗术
        {
            // 直接治疗目标
            if (Request.TargetEntity.IsValid())
            {
                FMassEntityView TargetView(EntityManager, Request.TargetEntity);
                if (TargetView.IsSet() && TargetView.HasFragment<FHealthFragment>())
                {
                    FHealthFragment& Health = TargetView.GetMutableFragmentData<FHealthFragment>();
                    Health.CurrentHealth = FMath::Min(Health.MaxHealth, Health.CurrentHealth + 50.0f);
                }
            }
            break;
        }
        case 3: // 范围攻击
        {
            // 查找范围内的所有敌人
            TArray<FMassEntityHandle> TargetsInRange = QueryEntitiesInRange(EntityManager, Request.TargetLocation, 300.0f);
            for (const FMassEntityHandle& Target : TargetsInRange)
            {
                // 对每个目标造成伤害
                FDamageRequestFragment Damage;
                Damage.AttackerEntity = Request.CasterEntity;
                Damage.DamageAmount = 30.0f;
                Damage.DamageType = 1;  // 魔法伤害
                EntityManager.AddFragmentToEntity(Target, Damage);
            }
            break;
        }
    }
    
    // 消耗法力值
    FMassEntityView CasterView(EntityManager, Request.CasterEntity);
    if (CasterView.IsSet() && CasterView.HasFragment<FManaFragment>())
    {
        FManaFragment& Mana = CasterView.GetMutableFragmentData<FManaFragment>();
        FAbilityData* AbilityData = AbilityDatabase.Find(Request.AbilityId);
        if (AbilityData)
        {
            Mana.CurrentMana = FMath::Max(0.0f, Mana.CurrentMana - AbilityData->ManaCost);
        }
    }
    
    // 记录冷却时间
    TPair<FMassEntityHandle, uint32> CooldownKey(Request.CasterEntity, Request.AbilityId);
    AbilityCooldowns.Add(CooldownKey, EntityManager.GetWorld().GetTimeSeconds());
}
```

---

## 三、P2P通信系统

### 3.1 Mass数据P2P同步

#### 网络同步处理器
```cpp
UCLASS()
class UMassNetworkSyncProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UMassNetworkSyncProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    // 不同优先级的查询
    FMassEntityQuery CriticalSyncQuery;
    FMassEntityQuery ImportantSyncQuery;
    FMassEntityQuery NormalSyncQuery;
    FMassEntityQuery PredictedSyncQuery;
    
    // 同步状态跟踪
    struct FEntitySyncState
    {
        FMassEntityHandle Entity;
        TMap<UScriptStruct*, FString> LastSyncData;  // 上次同步的数据哈希
        float LastSyncTime;
        int32 SyncSequence;
    };
    
    TMap<FMassEntityHandle, FEntitySyncState> EntitySyncStates;
    
    // 同步逻辑
    void SyncEntitiesWithPriority(const FMassEntityQuery& Query, EFragmentSyncPriority Priority, FMassEntityManager& EntityManager, FMassExecutionContext& Context);
    bool ShouldSyncFragment(const FMassEntityHandle& Entity, UScriptStruct* FragmentType, const void* FragmentData);
    void SendFragmentUpdate(const FMassEntityHandle& Entity, UScriptStruct* FragmentType, const void* FragmentData, EFragmentSyncPriority Priority);
    
    // 数据压缩
    TArray<uint8> CompressFragmentData(UScriptStruct* FragmentType, const void* FragmentData);
    TArray<uint8> DeltaCompressFragmentData(UScriptStruct* FragmentType, const void* CurrentData, const void* PreviousData);
    
    // 网络管理
    float LastCriticalSyncTime = 0.0f;
    float LastImportantSyncTime = 0.0f;
    float LastNormalSyncTime = 0.0f;
    float LastPredictedSyncTime = 0.0f;
};

void UMassNetworkSyncProcessor::ConfigureQueries()
{
    // 关键数据查询（生命值、状态等）
    CriticalSyncQuery.AddRequirement<FHealthFragment>(EMassFragmentAccess::ReadOnly);
    CriticalSyncQuery.AddRequirement<FEntityIdFragment>(EMassFragmentAccess::ReadOnly);
    
    // 重要数据查询（攻击、防御等）
    ImportantSyncQuery.AddRequirement<FAttackFragment>(EMassFragmentAccess::ReadOnly);
    ImportantSyncQuery.AddRequirement<FDefenseFragment>(EMassFragmentAccess::ReadOnly);
    ImportantSyncQuery.AddRequirement<FEntityIdFragment>(EMassFragmentAccess::ReadOnly);
    
    // 一般数据查询（装备、技能冷却等）
    NormalSyncQuery.AddRequirement<FInventoryFragment>(EMassFragmentAccess::ReadOnly);
    NormalSyncQuery.AddRequirement<FEntityIdFragment>(EMassFragmentAccess::ReadOnly);
    
    // 预测数据查询（位置、移动等）
    PredictedSyncQuery.AddRequirement<FTransformFragment>(EMassFragmentAccess::ReadOnly);
    PredictedSyncQuery.AddRequirement<FMovementFragment>(EMassFragmentAccess::ReadOnly);
    PredictedSyncQuery.AddRequirement<FEntityIdFragment>(EMassFragmentAccess::ReadOnly);
}

void UMassNetworkSyncProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    float CurrentTime = Context.GetWorld()->GetTimeSeconds();
    
    // 根据频率同步不同优先级的数据
    
    // 关键数据：10Hz
    if (CurrentTime - LastCriticalSyncTime >= 0.1f)
    {
        SyncEntitiesWithPriority(CriticalSyncQuery, EFragmentSyncPriority::Critical, EntityManager, Context);
        LastCriticalSyncTime = CurrentTime;
    }
    
    // 重要数据：5Hz
    if (CurrentTime - LastImportantSyncTime >= 0.2f)
    {
        SyncEntitiesWithPriority(ImportantSyncQuery, EFragmentSyncPriority::Important, EntityManager, Context);
        LastImportantSyncTime = CurrentTime;
    }
    
    // 一般数据：2Hz
    if (CurrentTime - LastNormalSyncTime >= 0.5f)
    {
        SyncEntitiesWithPriority(NormalSyncQuery, EFragmentSyncPriority::Normal, EntityManager, Context);
        LastNormalSyncTime = CurrentTime;
    }
    
    // 预测数据：20Hz
    if (CurrentTime - LastPredictedSyncTime >= 0.05f)
    {
        SyncEntitiesWithPriority(PredictedSyncQuery, EFragmentSyncPriority::Predicted, EntityManager, Context);
        LastPredictedSyncTime = CurrentTime;
    }
}

void UMassNetworkSyncProcessor::SyncEntitiesWithPriority(const FMassEntityQuery& Query, EFragmentSyncPriority Priority, FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    Query.ForEachEntityChunk(EntityManager, Context, [this, Priority, &EntityManager](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();
        
        // 获取所有Fragment视图
        TArray<TPair<UScriptStruct*, const void*>> FragmentViews;
        
        // 根据优先级获取相应的Fragment
        switch (Priority)
        {
            case EFragmentSyncPriority::Critical:
                if (Context.DoesArchetypeHaveFragment<FHealthFragment>())
                {
                    TConstArrayView<FHealthFragment> HealthFragments = Context.GetFragmentView<FHealthFragment>();
                    for (int32 i = 0; i < NumEntities; ++i)
                    {
                        FragmentViews.Add({FHealthFragment::StaticStruct(), &HealthFragments[i]});
                    }
                }
                break;
                
            case EFragmentSyncPriority::Predicted:
                if (Context.DoesArchetypeHaveFragment<FTransformFragment>())
                {
                    TConstArrayView<FTransformFragment> TransformFragments = Context.GetFragmentView<FTransformFragment>();
                    for (int32 i = 0; i < NumEntities; ++i)
                    {
                        FragmentViews.Add({FTransformFragment::StaticStruct(), &TransformFragments[i]});
                    }
                }
                if (Context.DoesArchetypeHaveFragment<FMovementFragment>())
                {
                    TConstArrayView<FMovementFragment> MovementFragments = Context.GetFragmentView<FMovementFragment>();
                    for (int32 i = 0; i < NumEntities; ++i)
                    {
                        FragmentViews.Add({FMovementFragment::StaticStruct(), &MovementFragments[i]});
                    }
                }
                break;
                
            // ... 其他优先级
        }
        
        // 对每个实体进行同步
        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            FMassEntityHandle Entity = Entities[EntityIndex];
            
            // 检查每个Fragment是否需要同步
            for (const auto& FragmentView : FragmentViews)
            {
                if (ShouldSyncFragment(Entity, FragmentView.Key, FragmentView.Value))
                {
                    SendFragmentUpdate(Entity, FragmentView.Key, FragmentView.Value, Priority);
                }
            }
        }
    });
}

bool UMassNetworkSyncProcessor::ShouldSyncFragment(const FMassEntityHandle& Entity, UScriptStruct* FragmentType, const void* FragmentData)
{
    // 获取实体的同步状态
    FEntitySyncState& SyncState = EntitySyncStates.FindOrAdd(Entity);
    
    // 计算当前数据的哈希值
    FString CurrentDataHash = FMD5::HashBytes(reinterpret_cast<const uint8*>(FragmentData), FragmentType->GetStructureSize()).ToString();
    
    // 检查是否与上次同步的数据相同
    FString* LastDataHash = SyncState.LastSyncData.Find(FragmentType);
    if (LastDataHash && *LastDataHash == CurrentDataHash)
    {
        return false;  // 数据未变化，不需要同步
    }
    
    // 更新同步状态
    SyncState.LastSyncData.Add(FragmentType, CurrentDataHash);
    SyncState.LastSyncTime = GetWorld()->GetTimeSeconds();
    
    return true;
}

void UMassNetworkSyncProcessor::SendFragmentUpdate(const FMassEntityHandle& Entity, UScriptStruct* FragmentType, const void* FragmentData, EFragmentSyncPriority Priority)
{
    // 获取同步配置
    FFragmentSyncConfig* SyncConfig = FragmentSyncConfigs.Find(FragmentType);
    if (!SyncConfig)
    {
        return;
    }
    
    // 序列化Fragment数据
    TArray<uint8> SerializedData;
    
    if (SyncConfig->bCompressData)
    {
        if (SyncConfig->bDeltaCompress)
        {
            // 差分压缩
            FEntitySyncState& SyncState = EntitySyncStates.FindOrAdd(Entity);
            // TODO: 实现差分压缩逻辑
            SerializedData = CompressFragmentData(FragmentType, FragmentData);
        }
        else
        {
            // 普通压缩
            SerializedData = CompressFragmentData(FragmentType, FragmentData);
        }
    }
    else
    {
        // 无压缩
        SerializedData.SetNumUninitialized(FragmentType->GetStructureSize());
        FMemory::Memcpy(SerializedData.GetData(), FragmentData, FragmentType->GetStructureSize());
    }
    
    // 创建网络包
    FMassNetworkPacket Packet;
    Packet.EntityId = Entity.Index;
    Packet.FragmentTypeHash = FragmentType->GetStructureSize();  // 简化的类型标识
    Packet.Data = SerializedData;
    Packet.Priority = Priority;
    Packet.bReliable = SyncConfig->bRequireReliable;
    Packet.Sequence = ++EntitySyncStates.FindOrAdd(Entity).SyncSequence;
    
    // 发送给所有P2P客户端
    BroadcastPacketToP2P(Packet);
}

TArray<uint8> UMassNetworkSyncProcessor::CompressFragmentData(UScriptStruct* FragmentType, const void* FragmentData)
{
    // 简化的压缩实现
    TArray<uint8> OriginalData;
    OriginalData.SetNumUninitialized(FragmentType->GetStructureSize());
    FMemory::Memcpy(OriginalData.GetData(), FragmentData, FragmentType->GetStructureSize());
    
    // 使用UE5的压缩工具
    TArray<uint8> CompressedData;
    FCompression::CompressMemory(NAME_Zlib, CompressedData, OriginalData.GetData(), OriginalData.Num());
    
    return CompressedData;
}
```

### 3.2 网络预测系统

#### 客户端预测处理器
```cpp
UCLASS()
class UMassClientPredictionProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UMassClientPredictionProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery PredictionQuery;
    
    // 预测状态
    struct FPredictionState
    {
        FMassEntityHandle Entity;
        FTransformFragment PredictedTransform;
        FMovementFragment PredictedMovement;
        float PredictionTime;
        int32 PredictionSequence;
    };
    
    TMap<FMassEntityHandle, FPredictionState> PredictionStates;
    
    // 预测逻辑
    void PredictMovement(FMassEntityHandle Entity, FTransformFragment& Transform, FMovementFragment& Movement, float DeltaTime);
    void CorrectPrediction(FMassEntityHandle Entity, const FTransformFragment& AuthorityTransform, const FMovementFragment& AuthorityMovement);
    
    // 插值
    FTransformFragment InterpolateTransform(const FTransformFragment& From, const FTransformFragment& To, float Alpha);
    
    // 延迟补偿
    float GetNetworkLatency() const;
    FTransformFragment ExtrapolateTransform(const FTransformFragment& Transform, const FMovementFragment& Movement, float ExtrapolationTime);
};

void UMassClientPredictionProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    // 只在客户端执行
    if (Context.GetWorld()->IsServer())
    {
        return;
    }
    
    float DeltaTime = Context.GetDeltaTimeSeconds();
    
    PredictionQuery.ForEachEntityChunk(EntityManager, Context, [this, DeltaTime](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TArrayView<FTransformFragment> Transforms = Context.GetMutableFragmentView<FTransformFragment>();
        TArrayView<FMovementFragment> Movements = Context.GetMutableFragmentView<FMovementFragment>();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            FTransformFragment& Transform = Transforms[EntityIndex];
            FMovementFragment& Movement = Movements[EntityIndex];
            FMassEntityHandle Entity = Entities[EntityIndex];

            // 对本地玩家控制的实体进行预测
            if (IsLocalPlayerControlled(Entity))
            {
                PredictMovement(Entity, Transform, Movement, DeltaTime);
            }
            else
            {
                // 对其他玩家的实体进行延迟补偿
                float NetworkLatency = GetNetworkLatency();
                FTransformFragment ExtrapolatedTransform = ExtrapolateTransform(Transform, Movement, NetworkLatency);
                
                // 平滑插值到推测位置
                Transform = InterpolateTransform(Transform, ExtrapolatedTransform, 0.1f);
            }
        }
    });
}

void UMassClientPredictionProcessor::PredictMovement(FMassEntityHandle Entity, FTransformFragment& Transform, FMovementFragment& Movement, float DeltaTime)
{
    // 保存预测状态
    FPredictionState& PredState = PredictionStates.FindOrAdd(Entity);
    PredState.Entity = Entity;
    PredState.PredictedTransform = Transform;
    PredState.PredictedMovement = Movement;
    PredState.PredictionTime = GetWorld()->GetTimeSeconds();
    PredState.PredictionSequence++;
    
    // 执行预测移动
    // 这里使用与服务器相同的移动逻辑
    FVector NewPosition = Transform.Position + Movement.CurrentVelocity * DeltaTime;
    
    // 简单的碰撞预测
    // TODO: 更复杂的碰撞预测逻辑
    
    Transform.Position = NewPosition;
    
    // 更新预测状态
    PredState.PredictedTransform = Transform;
}

void UMassClientPredictionProcessor::CorrectPrediction(FMassEntityHandle Entity, const FTransformFragment& AuthorityTransform, const FMovementFragment& AuthorityMovement)
{
    FPredictionState* PredState = PredictionStates.Find(Entity);
    if (!PredState)
    {
        return;
    }
    
    // 计算预测误差
    FVector PredictionError = AuthorityTransform.Position - PredState->PredictedTransform.Position;
    float ErrorMagnitude = PredictionError.Size();
    
    // 如果误差过大，需要校正
    if (ErrorMagnitude > 50.0f)  // 5cm阈值
    {
        // 获取实体的当前变换
        FMassEntityView EntityView(GetEntityManager(), Entity);
        if (EntityView.IsSet() && EntityView.HasFragment<FTransformFragment>())
        {
            FTransformFragment& CurrentTransform = EntityView.GetMutableFragmentData<FTransformFragment>();
            
            // 平滑校正到权威位置
            float CorrectionAlpha = FMath::Clamp(ErrorMagnitude / 100.0f, 0.1f, 1.0f);
            CurrentTransform.Position = FMath::Lerp(CurrentTransform.Position, AuthorityTransform.Position, CorrectionAlpha);
            
            // 更新预测状态
            PredState->PredictedTransform = CurrentTransform;
        }
    }
}

FTransformFragment UMassClientPredictionProcessor::InterpolateTransform(const FTransformFragment& From, const FTransformFragment& To, float Alpha)
{
    FTransformFragment Result;
    Result.Position = FMath::Lerp(From.Position, To.Position, Alpha);
    Result.Rotation = FMath::Lerp(From.Rotation, To.Rotation, Alpha);
    Result.Scale = FMath::Lerp(From.Scale, To.Scale, Alpha);
    return Result;
}

float UMassClientPredictionProcessor::GetNetworkLatency() const
{
    // 获取网络延迟
    if (APlayerController* PC = GetWorld()->GetFirstPlayerController())
    {
        if (APlayerState* PS = PC->GetPlayerState<APlayerState>())
        {
            return PS->GetPing() * 0.001f;  // 转换为秒
        }
    }
    return 0.05f;  // 默认50ms
}

FTransformFragment UMassClientPredictionProcessor::ExtrapolateTransform(const FTransformFragment& Transform, const FMovementFragment& Movement, float ExtrapolationTime)
{
    FTransformFragment Result = Transform;
    Result.Position += Movement.CurrentVelocity * ExtrapolationTime;
    return Result;
}
```

---

## 四、网络包结构与优化

### 4.1 数据包设计

#### 核心网络包结构
```cpp
// 基础网络包
USTRUCT()
struct FMassNetworkPacket
{
    GENERATED_BODY()
    
    UPROPERTY()
    uint32 EntityId;                // 实体ID
    
    UPROPERTY()
    uint32 FragmentTypeHash;        // Fragment类型哈希
    
    UPROPERTY()
    TArray<uint8> Data;             // 序列化数据
    
    UPROPERTY()
    EFragmentSyncPriority Priority; // 同步优先级
    
    UPROPERTY()
    bool bReliable;                 // 是否需要可靠传输
    
    UPROPERTY()
    uint32 Sequence;                // 序列号
    
    UPROPERTY()
    float Timestamp;                // 时间戳
    
    UPROPERTY()
    uint8 PlayerId;                 // 发送者ID
};

// 批量网络包（减少网络开销）
USTRUCT()
struct FMassBatchNetworkPacket
{
    GENERATED_BODY()
    
    UPROPERTY()
    TArray<FMassNetworkPacket> Packets;
    
    UPROPERTY()
    uint32 BatchSequence;
    
    UPROPERTY()
    float BatchTimestamp;
    
    UPROPERTY()
    uint8 SenderId;
    
    UPROPERTY()
    bool bCompressed;               // 整个批次是否压缩
};

// 指令包（玩家输入）
USTRUCT()
struct FMassCommandPacket
{
    GENERATED_BODY()
    
    UPROPERTY()
    uint8 PlayerId;
    
    UPROPERTY()
    uint8 CommandType;              // 0=移动, 1=攻击, 2=技能, 3=建造
    
    UPROPERTY()
    TArray<uint32> EntityIds;       // 涉及的实体ID
    
    UPROPERTY()
    FVector TargetLocation;         // 目标位置
    
    UPROPERTY()
    uint32 TargetEntityId;          // 目标实体ID
    
    UPROPERTY()
    uint32 AbilityId;               // 技能ID
    
    UPROPERTY()
    uint32 CommandSequence;         // 指令序列号
    
    UPROPERTY()
    float ClientTimestamp;          // 客户端时间戳
};
```

### 4.2 带宽优化策略

#### 网络优化管理器
```cpp
UCLASS()
class UMassNetworkOptimizer : public UGameInstanceSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    
    // 带宽管理
    void SetBandwidthLimit(float MaxBandwidthKBps);
    bool CanSendPacket(const FMassNetworkPacket& Packet);
    void RecordPacketSent(const FMassNetworkPacket& Packet);
    
    // 优先级管理
    void UpdateSyncPriorities();
    EFragmentSyncPriority GetDynamicPriority(const FMassEntityHandle& Entity, UScriptStruct* FragmentType);
    
    // 距离剔除
    bool ShouldSyncToPlayer(const FMassEntityHandle& Entity, uint8 PlayerId);
    void UpdatePlayerViewports();
    
    // 统计信息
    FNetworkStats GetNetworkStats() const;

private:
    // 带宽跟踪
    struct FBandwidthTracker
    {
        float MaxBandwidthKBps = 500.0f;        // 最大带宽限制
        float CurrentBandwidthUsage = 0.0f;     // 当前带宽使用
        TArray<float> BandwidthHistory;         // 带宽历史
        float LastUpdateTime = 0.0f;
    };
    
    FBandwidthTracker BandwidthTracker;
    
    // 玩家视口信息
    struct FPlayerViewport
    {
        uint8 PlayerId;
        FVector CameraPosition;
        FVector CameraDirection;
        float ViewDistance;
        float FOV;
    };
    
    TArray<FPlayerViewport> PlayerViewports;
    
    // 实体重要性评分
    struct FEntityImportance
    {
        FMassEntityHandle Entity;
        float ImportanceScore;
        float LastUpdateTime;
    };
    
    TMap<FMassEntityHandle, FEntityImportance> EntityImportanceScores;
    
    // 优化算法
    float CalculateEntityImportance(const FMassEntityHandle& Entity, uint8 ForPlayerId);
    void UpdateEntityImportanceScores();
    TArray<FMassEntityHandle> GetEntitiesInPlayerView(uint8 PlayerId);
    
    // 自适应质量
    void AdaptSyncQuality();
    float GetAdaptiveUpdateRate(EFragmentSyncPriority Priority);
};

void UMassNetworkOptimizer::UpdateSyncPriorities()
{
    // 基于网络状况动态调整同步优先级
    float CurrentLatency = GetAverageNetworkLatency();
    float CurrentPacketLoss = GetPacketLossRate();
    
    // 网络状况差时降低非关键数据的同步频率
    if (CurrentLatency > 0.1f || CurrentPacketLoss > 0.05f)
    {
        // 降低一般数据的同步频率
        FragmentSyncConfigs[FInventoryFragment::StaticStruct()].SyncFrequency = 1.0f;
        FragmentSyncConfigs[FEffectFragment::StaticStruct()].SyncFrequency = 1.0f;
        
        // 提高关键数据的可靠性
        FragmentSyncConfigs[FHealthFragment::StaticStruct()].bRequireReliable = true;
    }
    else
    {
        // 网络状况良好时恢复正常频率
        FragmentSyncConfigs[FInventoryFragment::StaticStruct()].SyncFrequency = 2.0f;
        FragmentSyncConfigs[FEffectFragment::StaticStruct()].SyncFrequency = 2.0f;
    }
}

bool UMassNetworkOptimizer::ShouldSyncToPlayer(const FMassEntityHandle& Entity, uint8 PlayerId)
{
    // 1. 检查实体是否在玩家视野内
    FPlayerViewport* PlayerViewport = PlayerViewports.FindByPredicate([PlayerId](const FPlayerViewport& Viewport)
    {
        return Viewport.PlayerId == PlayerId;
    });
    
    if (!PlayerViewport)
    {
        return false;
    }
    
    // 2. 获取实体位置
    if (UMassEntitySubsystem* EntitySubsystem = GetGameInstance()->GetWorld()->GetSubsystem<UMassEntitySubsystem>())
    {
        FMassEntityManager& EntityManager = EntitySubsystem->GetEntityManager();
        FMassEntityView EntityView(EntityManager, Entity);
        
        if (EntityView.IsSet() && EntityView.HasFragment<FTransformFragment>())
        {
            const FTransformFragment& Transform = EntityView.GetFragmentData<FTransformFragment>();
            
            // 3. 距离剔除
            float Distance = FVector::Dist(Transform.Position, PlayerViewport->CameraPosition);
            if (Distance > PlayerViewport->ViewDistance * 1.2f)  // 20%容错
            {
                return false;
            }
            
            // 4. 视锥剔除
            FVector ToEntity = (Transform.Position - PlayerViewport->CameraPosition).GetSafeNormal();
            float DotProduct = FVector::DotProduct(ToEntity, PlayerViewport->CameraDirection);
            float CosHalfFOV = FMath::Cos(FMath::DegreesToRadians(PlayerViewport->FOV * 0.5f));
            
            if (DotProduct < CosHalfFOV * 0.8f)  // 20%容错
            {
                return false;
            }
            
            return true;
        }
    }
    
    return false;
}

float UMassNetworkOptimizer::CalculateEntityImportance(const FMassEntityHandle& Entity, uint8 ForPlayerId)
{
    float ImportanceScore = 0.0f;
    
    if (UMassEntitySubsystem* EntitySubsystem = GetGameInstance()->GetWorld()->GetSubsystem<UMassEntitySubsystem>())
    {
        FMassEntityManager& EntityManager = EntitySubsystem->GetEntityManager();
        FMassEntityView EntityView(EntityManager, Entity);
        
        if (EntityView.IsSet())
        {
            // 1. 基于实体类型的重要性
            if (EntityView.HasFragment<FEntityIdFragment>())
            {
                const FEntityIdFragment& EntityId = EntityView.GetFragmentData<FEntityIdFragment>();
                switch (EntityId.EntityType)
                {
                    case 0: ImportanceScore += 10.0f; break;  // 小兵
                    case 1: ImportanceScore += 50.0f; break;  // 英雄
                    case 2: ImportanceScore += 30.0f; break;  // 建筑
                    case 3: ImportanceScore += 20.0f; break;  // 投射物
                }
                
                // 己方单位更重要
                if (EntityId.PlayerId == ForPlayerId)
                {
                    ImportanceScore *= 1.5f;
                }
            }
            
            // 2. 基于距离的重要性
            if (EntityView.HasFragment<FTransformFragment>())
            {
                const FTransformFragment& Transform = EntityView.GetFragmentData<FTransformFragment>();
                FPlayerViewport* PlayerViewport = PlayerViewports.FindByPredicate([ForPlayerId](const FPlayerViewport& Viewport)
                {
                    return Viewport.PlayerId == ForPlayerId;
                });
                
                if (PlayerViewport)
                {
                    float Distance = FVector::Dist(Transform.Position, PlayerViewport->CameraPosition);
                    float DistanceScore = FMath::Clamp(1000.0f / (Distance + 100.0f), 0.1f, 10.0f);
                    ImportanceScore *= DistanceScore;
                }
            }
            
            // 3. 基于战斗状态的重要性
            if (EntityView.HasFragment<FAttackingStateFragment>())
            {
                ImportanceScore *= 2.0f;  // 正在战斗的单位更重要
            }
            
            // 4. 基于生命值的重要性
            if (EntityView.HasFragment<FHealthFragment>())
            {
                const FHealthFragment& Health = EntityView.GetFragmentData<FHealthFragment>();
                float HealthRatio = Health.CurrentHealth / Health.MaxHealth;
                if (HealthRatio < 0.3f)
                {
                    ImportanceScore *= 1.5f;  // 濒死单位更重要
                }
            }
        }
    }
    
    return ImportanceScore;
}

void UMassNetworkOptimizer::AdaptSyncQuality()
{
    // 基于网络状况和性能自适应调整同步质量
    float CurrentFPS = 1.0f / GetWorld()->GetDeltaSeconds();
    float TargetFPS = 60.0f;
    
    if (CurrentFPS < TargetFPS * 0.8f)
    {
        // 帧率过低，降低同步质量
        for (auto& ConfigPair : FragmentSyncConfigs)
        {
            if (ConfigPair.Value.Priority != EFragmentSyncPriority::Critical)
            {
                ConfigPair.Value.SyncFrequency *= 0.8f;
            }
        }
    }
    else if (CurrentFPS > TargetFPS * 1.1f)
    {
        // 帧率充足，可以提高同步质量
        for (auto& ConfigPair : FragmentSyncConfigs)
        {
            ConfigPair.Value.SyncFrequency *= 1.05f;
        }
    }
    
    // 基于带宽使用情况调整
    float BandwidthUsageRatio = BandwidthTracker.CurrentBandwidthUsage / BandwidthTracker.MaxBandwidthKBps;
    if (BandwidthUsageRatio > 0.8f)
    {
        // 带宽使用过高，降低同步频率
        for (auto& ConfigPair : FragmentSyncConfigs)
        {
            if (ConfigPair.Value.Priority == EFragmentSyncPriority::Normal)
            {
                ConfigPair.Value.SyncFrequency *= 0.7f;
            }
        }
    }
}
```

---

## 五、实施建议与测试

### 5.1 网络测试框架

#### 网络模拟器
```cpp
UCLASS()
class UMassNetworkSimulator : public UObject
{
    GENERATED_BODY()

public:
    // 网络条件模拟
    UFUNCTION(CallInEditor = true, Category = "Network Test")
    void SimulateLatency(float LatencyMs);
    
    UFUNCTION(CallInEditor = true, Category = "Network Test")
    void SimulatePacketLoss(float LossPercentage);
    
    UFUNCTION(CallInEditor = true, Category = "Network Test")
    void SimulateBandwidthLimit(float BandwidthKBps);
    
    // 压力测试
    UFUNCTION(CallInEditor = true, Category = "Network Test")
    void TestWithEntityCount(int32 EntityCount);
    
    UFUNCTION(CallInEditor = true, Category = "Network Test")
    void TestWithPlayerCount(int32 PlayerCount);
    
    // 性能测试
    UFUNCTION(CallInEditor = true, Category = "Network Test")
    void MeasureNetworkPerformance();
    
    // 测试结果
    UPROPERTY(EditAnywhere, Category = "Test Results")
    FNetworkTestResults TestResults;

private:
    struct FNetworkTestResults
    {
        float AverageLatency;
        float PacketLossRate;
        float BandwidthUsage;
        float SyncAccuracy;
        int32 DesyncCount;
        float MaxEntityCount;
        float MaxPlayerCount;
    };
    
    // 测试实现
    void RunLatencyTest();
    void RunSyncAccuracyTest();
    void RunScalabilityTest();
};
```

### 5.2 部署配置

#### 网络配置模板
```cpp
// 网络配置数据
USTRUCT()
struct FMassNetworkConfig
{
    GENERATED_BODY()
    
    // 服务器配置
    UPROPERTY(EditAnywhere, Category = "Server")
    FString ServerAddress = "127.0.0.1";
    
    UPROPERTY(EditAnywhere, Category = "Server")
    int32 ServerPort = 7777;
    
    UPROPERTY(EditAnywhere, Category = "Server")
    float ServerTickRate = 30.0f;
    
    // P2P配置
    UPROPERTY(EditAnywhere, Category = "P2P")
    bool bEnableP2P = true;
    
    UPROPERTY(EditAnywhere, Category = "P2P")
    int32 MaxP2PConnections = 11;
    
    UPROPERTY(EditAnywhere, Category = "P2P")
    float P2PTimeoutSeconds = 30.0f;
    
    // 同步配置
    UPROPERTY(EditAnywhere, Category = "Sync")
    float CriticalSyncRate = 10.0f;
    
    UPROPERTY(EditAnywhere, Category = "Sync")
    float ImportantSyncRate = 5.0f;
    
    UPROPERTY(EditAnywhere, Category = "Sync")
    float NormalSyncRate = 2.0f;
    
    UPROPERTY(EditAnywhere, Category = "Sync")
    float PredictedSyncRate = 20.0f;
    
    // 优化配置
    UPROPERTY(EditAnywhere, Category = "Optimization")
    float MaxBandwidthKBps = 500.0f;
    
    UPROPERTY(EditAnywhere, Category = "Optimization")
    float ViewDistanceMeters = 2000.0f;
    
    UPROPERTY(EditAnywhere, Category = "Optimization")
    bool bEnableDistanceCulling = true;
    
    UPROPERTY(EditAnywhere, Category = "Optimization")
    bool bEnableViewFrustumCulling = true;
    
    UPROPERTY(EditAnywhere, Category = "Optimization")
    bool bEnableAdaptiveQuality = true;
};
```

### 5.3 性能目标

#### 网络性能基准
```
目标配置：
- 玩家数量：12人
- 实体数量：800个
- 网络延迟：<100ms
- 带宽使用：<500KB/s per player
- 同步精度：位置误差<5cm
- 帧率影响：<10%

测试场景：
1. 最佳网络环境：延迟20ms，丢包率0%
2. 一般网络环境：延迟50ms，丢包率1%
3. 恶劣网络环境：延迟150ms，丢包率5%
4. 移动网络环境：延迟100ms，丢包率2%，带宽限制200KB/s
```

这套网络架构设计为Mass系统提供了完整的网络同步解决方案，确保在大规模RTS游戏中实现高性能、低延迟的多人联机体验。

---

**文档版本**：v1.0  
**最后更新**：2025年1月17日  
**维护者**：Claude AI Assistant  
**适用阶段**：开发第二阶段