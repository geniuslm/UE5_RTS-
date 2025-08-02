# UE5 RTS Mass架构核心设计方案

## 概述

基于深度架构讨论，本文档详细阐述纯Mass架构的核心设计理念和实现方案。

## 一、Fragment体系设计

### 1.1 核心Fragment架构

#### 基础数据层
```cpp
// 位置变换Fragment
USTRUCT()
struct FRTSTransformFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FVector Location;
    FRotator Rotation;
    FVector Scale = FVector::OneVector;
    
    // 用于网络同步的压缩位置
    uint32 CompressedLocation;
    uint16 CompressedRotation;
};

// 实体身份Fragment
USTRUCT()
struct FRTSEntityIdFragment : public FMassFragment
{
    GENERATED_BODY()
    
    uint32 UniqueId;           // 全局唯一ID
    uint8 EntityType;          // 实体类型枚举
    uint8 PlayerOwner;         // 拥有者ID
    uint16 TeamId;             // 队伍ID
};

// 单位类型Fragment
USTRUCT()
struct FRTSUnitTypeFragment : public FMassFragment
{
    GENERATED_BODY()
    
    uint8 UnitClass;           // 单位类别（步兵、骑兵、法师等）
    uint8 UnitTier;            // 单位等级
    uint16 UnitSpecialFlags;   // 特殊属性标记位
    float BaseScale;           // 基础缩放
};
```

#### 战斗数据层
```cpp
// 生命值Fragment
USTRUCT()
struct FRTSHealthFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float CurrentHealth;
    float MaxHealth;
    float HealthRegenRate;     // 生命回复速度
    uint32 LastDamageTime;     // 最后受伤时间
    
    // 网络同步优化：使用百分比传输
    uint8 HealthPercentage;
};

// 攻击属性Fragment
USTRUCT()
struct FRTSAttackStatsFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float AttackDamage;
    float AttackSpeed;         // 攻击间隔
    float AttackRange;
    uint8 AttackType;          // 物理/魔法/真实伤害
    uint32 LastAttackTime;     // 上次攻击时间
};

// 防御属性Fragment
USTRUCT()
struct FRTSDefenseFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float PhysicalArmor;
    float MagicalResistance;
    float DamageReduction;     // 百分比减伤
    uint8 ArmorType;           // 护甲类型
};

// 伤害请求Fragment（临时数据）
USTRUCT()
struct FRTSDamageRequestFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FMassEntityHandle AttackerEntity;
    float BaseDamage;
    uint8 DamageType;
    FVector DamageDirection;   // 伤害方向（用于击退）
    uint32 DamageFlags;        // 伤害标志位
};
```

#### 移动数据层
```cpp
// 移动属性Fragment
USTRUCT()
struct FRTSMovementFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float MaxSpeed;
    float CurrentSpeed;
    float Acceleration;
    float TurnRate;
    FVector Velocity;
    uint8 MovementType;        // 地面/飞行/水中
};

// 导航Fragment
USTRUCT()
struct FRTSNavigationFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FVector TargetLocation;
    TArray<FVector> PathPoints;
    int32 CurrentPathIndex;
    float PathfindingRadius;
    uint32 PathUpdateTime;
};

// 避障Fragment
USTRUCT()
struct FRTSAvoidanceFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float AvoidanceRadius;
    float AvoidanceForce;
    FVector AvoidanceDirection;
    uint8 AvoidancePriority;
};

// 编队Fragment
USTRUCT()
struct FRTSFormationFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FMassEntityHandle FormationLeader;
    FVector FormationOffset;
    uint8 FormationType;
    uint8 FormationIndex;
};
```

### 1.2 状态Fragment系统

#### 取代Tag的Fragment设计
```cpp
// 移动状态Fragment
USTRUCT()
struct FRTSMovingStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FVector MoveDirection;
    float MoveSpeed;
    uint32 MoveStartTime;
    uint8 MoveType;            // 普通移动/冲刺/后退
};

// 攻击状态Fragment
USTRUCT()
struct FRTSAttackingStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FMassEntityHandle TargetEntity;
    float AttackProgress;      // 攻击动画进度
    uint8 AttackPhase;         // 攻击阶段
    uint32 AttackStartTime;
};

// 眩晕状态Fragment
USTRUCT()
struct FRTSStunnedStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float RemainingDuration;
    FMassEntityHandle SourceEntity;
    uint8 StunType;            // 眩晕类型
    uint8 StunLevel;           // 眩晕等级
};

// 选中状态Fragment
USTRUCT()
struct FRTSSelectedStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    uint8 SelectionType;       // 单选/多选/框选
    uint32 SelectionTime;      // 选中时间
    uint8 SelectionGroup;      // 选中组别
};
```

## 二、Processor执行架构

### 2.1 核心处理器设计

#### 输入处理器
```cpp
UCLASS()
class UInputProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UInputProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, 
                        FMassExecutionContext& Context) override;

private:
    FMassEntityQuery PlayerInputQuery;
    
    // 处理移动指令
    void ProcessMoveCommand(const FPlayerCommand& Command, 
                           FMassEntityManager& EntityManager);
    
    // 处理攻击指令
    void ProcessAttackCommand(const FPlayerCommand& Command, 
                             FMassEntityManager& EntityManager);
};
```

#### 攻击处理器
```cpp
UCLASS()
class UAttackProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UAttackProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, 
                        FMassExecutionContext& Context) override;

private:
    FMassEntityQuery AttackingEntitiesQuery;
    
    // 空间查询子系统
    UPROPERTY()
    class USpatialPartitionSubsystem* SpatialSubsystem;
    
    // 查找攻击目标
    void FindAttackTargets(FMassExecutionContext& Context);
    
    // 执行攻击逻辑
    void ExecuteAttack(const FRTSAttackStatsFragment& AttackStats,
                      const FRTSTransformFragment& AttackerTransform,
                      FMassEntityHandle AttackerEntity,
                      FMassEntityManager& EntityManager);
};
```

#### 伤害处理器
```cpp
UCLASS()
class UDamageProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UDamageProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, 
                        FMassExecutionContext& Context) override;

private:
    FMassEntityQuery DamageRequestQuery;
    
    // 计算最终伤害
    float CalculateFinalDamage(const FRTSDamageRequestFragment& DamageRequest,
                              const FRTSDefenseFragment& Defense,
                              FMassEntityManager& EntityManager);
    
    // 应用伤害效果
    void ApplyDamageEffect(FRTSHealthFragment& Health,
                          const FRTSDamageRequestFragment& DamageRequest,
                          FMassEntityHandle TargetEntity,
                          FMassEntityManager& EntityManager);
};
```

### 2.2 处理器执行顺序

#### 优化的执行流程
```cpp
// 在MassSpawner中配置处理器执行顺序
void ConfigureProcessorOrder()
{
    // 1. 输入处理 - 最高优先级
    AddProcessor<UInputProcessor>(EMassProcessingPhase::PrePhysics, 1000);
    
    // 2. AI决策处理
    AddProcessor<UAIDecisionProcessor>(EMassProcessingPhase::PrePhysics, 900);
    
    // 3. 导航和路径规划
    AddProcessor<UNavigationProcessor>(EMassProcessingPhase::PrePhysics, 800);
    
    // 4. 移动计算
    AddProcessor<UMovementProcessor>(EMassProcessingPhase::PrePhysics, 700);
    
    // 5. 攻击处理
    AddProcessor<UAttackProcessor>(EMassProcessingPhase::PrePhysics, 600);
    
    // 6. 伤害处理
    AddProcessor<UDamageProcessor>(EMassProcessingPhase::PrePhysics, 500);
    
    // 7. 状态效果处理
    AddProcessor<UEffectProcessor>(EMassProcessingPhase::PrePhysics, 400);
    
    // 8. 渲染数据更新
    AddProcessor<URenderProcessor>(EMassProcessingPhase::PostPhysics, 300);
    
    // 9. 网络同步
    AddProcessor<UNetworkProcessor>(EMassProcessingPhase::PostPhysics, 200);
}
```

## 三、实体通信机制

### 3.1 句柄引用系统

#### 安全的实体引用
```cpp
// 实体引用管理器
class FEntityReferenceManager
{
public:
    // 验证实体句柄有效性
    bool IsEntityValid(const FMassEntityHandle& EntityHandle, 
                      const FMassEntityManager& EntityManager) const;
    
    // 安全获取实体数据
    template<typename FragmentType>
    const FragmentType* GetFragmentSafe(const FMassEntityHandle& EntityHandle,
                                       const FMassEntityManager& EntityManager) const;
    
    // 建立实体关系
    void EstablishRelationship(FMassEntityHandle SourceEntity,
                              FMassEntityHandle TargetEntity,
                              uint8 RelationshipType,
                              FMassEntityManager& EntityManager);
};
```

#### 数据一致性保证
```cpp
// 在伤害处理器中使用句柄获取实时数据
void UDamageProcessor::Execute(FMassEntityManager& EntityManager, 
                              FMassExecutionContext& Context)
{
    DamageRequestQuery.ForEachEntityChunk(EntityManager, Context,
        [&](FMassExecutionContext& Context)
        {
            const TArrayView<FRTSDamageRequestFragment> DamageRequests = 
                Context.GetFragmentView<FRTSDamageRequestFragment>();
            
            for (int32 i = 0; i < Context.GetNumEntities(); ++i)
            {
                const FRTSDamageRequestFragment& DamageRequest = DamageRequests[i];
                
                // 通过句柄获取攻击者当前数据
                FMassEntityView AttackerView(EntityManager, DamageRequest.AttackerEntity);
                if (AttackerView.IsSet())
                {
                    // 获取攻击者最新的攻击属性（包含buff/debuff）
                    const FRTSAttackStatsFragment& CurrentAttackStats = 
                        AttackerView.GetFragmentData<FRTSAttackStatsFragment>();
                    
                    // 使用最新数据计算伤害
                    float FinalDamage = CalculateFinalDamage(
                        DamageRequest, CurrentAttackStats, EntityManager);
                }
            }
        });
}
```

### 3.2 Signal事件系统

#### 事件定义
```cpp
// RTS游戏专用信号常量
namespace UE::RTS::Signals
{
    // 实体生命周期事件
    const FName OnEntitySpawned = "OnEntitySpawned";
    const FName OnEntityDied = "OnEntityDied";
    const FName OnEntityDestroyed = "OnEntityDestroyed";
    
    // 战斗事件
    const FName OnAttackStarted = "OnAttackStarted";
    const FName OnAttackHit = "OnAttackHit";
    const FName OnDamageTaken = "OnDamageTaken";
    const FName OnHealthChanged = "OnHealthChanged";
    
    // 移动事件
    const FName OnMoveStarted = "OnMoveStarted";
    const FName OnMoveCompleted = "OnMoveCompleted";
    const FName OnPositionChanged = "OnPositionChanged";
    
    // 技能事件
    const FName OnAbilityUsed = "OnAbilityUsed";
    const FName OnAbilityCompleted = "OnAbilityCompleted";
    const FName OnAbilityCancelled = "OnAbilityCancelled";
    
    // 资源事件
    const FName OnResourceGathered = "OnResourceGathered";
    const FName OnBuildingCompleted = "OnBuildingCompleted";
    const FName OnUnitProduced = "OnUnitProduced";
}
```

#### 事件处理示例
```cpp
// 死亡特效处理器
UCLASS()
class UDeathEffectProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UDeathEffectProcessor()
    {
        // 注册死亡事件监听
        RegisterSignalWithCallback<UDeathEffectProcessor>(
            UE::RTS::Signals::OnEntityDied, this);
    }

protected:
    virtual void ConfigureQueries() override
    {
        // 只处理有渲染表现的死亡实体
        EntityQuery.AddRequirement<FRTSTransformFragment>(EMassFragmentAccess::ReadOnly);
        EntityQuery.AddRequirement<FRTSRenderFragment>(EMassFragmentAccess::ReadOnly);
    }
    
    virtual void Execute(FMassEntityManager& EntityManager, 
                        FMassExecutionContext& Context) override
    {
        // 为死亡实体生成特效
        EntityQuery.ForEachEntityChunk(EntityManager, Context,
            [&](FMassExecutionContext& Context)
            {
                // 生成死亡特效
                // 播放死亡音效
                // 创建掉落物品
                // 更新击杀统计
            });
    }
};
```

## 四、性能优化策略

### 4.1 内存优化

#### Fragment紧凑设计
```cpp
// 优化前的Fragment（浪费内存）
struct FBadFragment : public FMassFragment
{
    bool bIsActive;        // 1字节，但占用4字节
    float Health;          // 4字节
    bool bCanAttack;       // 1字节，但占用4字节
    double BigValue;       // 8字节
};  // 总共20字节

// 优化后的Fragment（内存紧凑）
struct FGoodFragment : public FMassFragment
{
    float Health;          // 4字节
    double BigValue;       // 8字节
    uint8 Flags;           // 1字节包含多个布尔值
    uint8 Reserved[3];     // 3字节填充对齐
};  // 总共16字节
```

#### 对象池管理
```cpp
// Fragment对象池
template<typename FragmentType>
class TFragmentPool
{
private:
    TArray<FragmentType> Pool;
    TArray<int32> FreeIndices;
    
public:
    FragmentType* Acquire();
    void Release(FragmentType* Fragment);
    void PreAllocate(int32 Count);
};
```

### 4.2 查询优化

#### 高效的查询设计
```cpp
// 避免过度具体的查询
class UBadProcessor : public UMassProcessor
{
    void ConfigureQueries() override
    {
        // 坏例子：过度具体的查询
        EntityQuery.AddRequirement<FRTSHealthFragment>(EMassFragmentAccess::ReadOnly);
        EntityQuery.AddRequirement<FRTSAttackStatsFragment>(EMassFragmentAccess::ReadOnly);
        EntityQuery.AddRequirement<FRTSMovementFragment>(EMassFragmentAccess::ReadOnly);
        EntityQuery.AddRequirement<FRTSDefenseFragment>(EMassFragmentAccess::ReadOnly);
        // ... 10个以上的Fragment要求
    }
};

// 好例子：最小化查询要求
class UGoodProcessor : public UMassProcessor
{
    void ConfigureQueries() override
    {
        // 只要求必需的Fragment
        EntityQuery.AddRequirement<FRTSHealthFragment>(EMassFragmentAccess::ReadWrite);
        EntityQuery.AddRequirement<FRTSDamageRequestFragment>(EMassFragmentAccess::ReadOnly);
    }
};
```

### 4.3 多线程优化

#### 并行处理器设计
```cpp
// 支持多线程的处理器
UCLASS()
class UParallelMovementProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UParallelMovementProcessor()
    {
        // 启用多线程执行
        ExecutionFlags = (int32)(EProcessorExecutionFlags::All);
        bCanRunInParallel = true;
    }

protected:
    virtual void Execute(FMassEntityManager& EntityManager, 
                        FMassExecutionContext& Context) override
    {
        // 使用ParallelFor进行并行计算
        EntityQuery.ParallelForEachEntityChunk(EntityManager, Context,
            [](FMassExecutionContext& Context)
            {
                // 线程安全的移动计算
                ProcessMovementChunk(Context);
            });
    }
    
private:
    static void ProcessMovementChunk(FMassExecutionContext& Context);
};
```

---

**文档版本**：v1.0  
**最后更新**：2025年1月17日  
**维护者**：Claude AI Assistant  
**状态**：核心设计完成