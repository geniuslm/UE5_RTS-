# UE5 RTS Mass架构实现指南
## Claude专项设计方案

> **专项目标**：纯Mass Entity架构的具体实现方案  
> **技术重点**：Fragment体系设计、Processor实现、实体通信机制  
> **适用阶段**：开发第一阶段（6-8周）  

---

## 一、核心Fragment体系设计

### 1.1 Fragment分层架构

#### 基础数据Fragment
```cpp
// 变换信息（所有实体必需）
USTRUCT()
struct FTransformFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(EditAnywhere)
    FVector Position;
    
    UPROPERTY(EditAnywhere)
    FRotator Rotation;
    
    UPROPERTY(EditAnywhere)
    FVector Scale = FVector::OneVector;
    
    // 用于网络同步的上一帧位置
    FVector PreviousPosition;
};

// 实体标识（所有实体必需）
USTRUCT()
struct FEntityIdFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(EditAnywhere)
    uint32 EntityId;
    
    UPROPERTY(EditAnywhere)
    uint8 EntityType;  // 0=小兵, 1=英雄, 2=建筑, 3=投射物
    
    UPROPERTY(EditAnywhere)
    uint8 PlayerId;    // 归属玩家ID
};

// 生命值系统（战斗单位必需）
USTRUCT()
struct FHealthFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(EditAnywhere)
    float CurrentHealth;
    
    UPROPERTY(EditAnywhere)
    float MaxHealth;
    
    UPROPERTY(EditAnywhere)
    float HealthRegenRate = 0.0f;
    
    // 状态标志
    bool bIsAlive = true;
    bool bIsInvincible = false;
};
```

#### 移动系统Fragment
```cpp
// 移动能力
USTRUCT()
struct FMovementFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(EditAnywhere)
    float MaxSpeed = 300.0f;
    
    UPROPERTY(EditAnywhere)
    float Acceleration = 1000.0f;
    
    UPROPERTY(EditAnywhere)
    float TurnRate = 360.0f;
    
    FVector CurrentVelocity;
    FVector DesiredVelocity;
};

// 导航信息
USTRUCT()
struct FNavigationFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FVector TargetLocation;
    TArray<FVector> PathPoints;
    int32 CurrentPathIndex = 0;
    
    // 路径状态
    bool bHasPath = false;
    bool bReachedDestination = false;
    float AcceptanceRadius = 50.0f;
};

// 避障信息
USTRUCT()
struct FAvoidanceFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float AvoidanceRadius = 100.0f;
    float AvoidanceForce = 500.0f;
    
    // 群体行为参数
    float SeparationWeight = 1.0f;
    float AlignmentWeight = 0.5f;
    float CohesionWeight = 0.3f;
};
```

#### 战斗系统Fragment
```cpp
// 攻击能力
USTRUCT()
struct FAttackFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(EditAnywhere)
    float AttackDamage = 10.0f;
    
    UPROPERTY(EditAnywhere)
    float AttackRange = 200.0f;
    
    UPROPERTY(EditAnywhere)
    float AttackSpeed = 1.0f;  // 每秒攻击次数
    
    float LastAttackTime = 0.0f;
    FMassEntityHandle CurrentTarget;
    
    // 攻击类型标志
    uint8 AttackType = 0;  // 0=近战, 1=远程, 2=魔法
};

// 防御能力
USTRUCT()
struct FDefenseFragment : public FMassFragment
{
    GENERATED_BODY()
    
    UPROPERTY(EditAnywhere)
    float Armor = 0.0f;
    
    UPROPERTY(EditAnywhere)
    float MagicResistance = 0.0f;
    
    UPROPERTY(EditAnywhere)
    float DamageReduction = 0.0f;  // 百分比减伤
};

// 伤害请求（临时Fragment）
USTRUCT()
struct FDamageRequestFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FMassEntityHandle AttackerEntity;
    float DamageAmount;
    uint8 DamageType;  // 0=物理, 1=魔法, 2=真实
    FVector DamageDirection;
};
```

### 1.2 状态Fragment（替代Tag）

```cpp
// 移动状态
USTRUCT()
struct FMovingStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FVector MovementDirection;
    float CurrentSpeed;
    bool bIsMoving = false;
};

// 攻击状态
USTRUCT()
struct FAttackingStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    FMassEntityHandle Target;
    float AttackProgress = 0.0f;  // 0-1之间
    uint8 AttackPhase = 0;  // 0=准备, 1=攻击, 2=恢复
};

// 眩晕状态
USTRUCT()
struct FStunnedStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float RemainingTime;
    FMassEntityHandle Source;  // 施法者
    uint8 StunLevel = 1;
};

// 选中状态
USTRUCT()
struct FSelectedStateFragment : public FMassFragment
{
    GENERATED_BODY()
    
    uint8 PlayerId;  // 哪个玩家选中
    float SelectionTime;  // 选中时间
    bool bIsGroupSelected = false;
};
```

---

## 二、Processor实现详解

### 2.1 核心处理器架构

#### 移动处理器
```cpp
UCLASS()
class UMovementProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UMovementProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery MovementQuery;
    
    // 移动算法
    FVector CalculateDesiredVelocity(const FNavigationFragment& Nav, const FTransformFragment& Transform);
    FVector CalculateAvoidanceForce(const FAvoidanceFragment& Avoidance, const FTransformFragment& Transform, const FMassEntityManager& EntityManager);
    void UpdatePath(FNavigationFragment& Nav, const FTransformFragment& Transform);
};

// 实现
UMovementProcessor::UMovementProcessor()
{
    ExecutionFlags = (int32)EProcessorExecutionFlags::All;
    ExecutionOrder.ExecuteInGroup = UE::Mass::ProcessorGroupNames::Movement;
}

void UMovementProcessor::ConfigureQueries()
{
    MovementQuery.AddRequirement<FTransformFragment>(EMassFragmentAccess::ReadWrite);
    MovementQuery.AddRequirement<FMovementFragment>(EMassFragmentAccess::ReadWrite);
    MovementQuery.AddRequirement<FNavigationFragment>(EMassFragmentAccess::ReadWrite);
    MovementQuery.AddRequirement<FAvoidanceFragment>(EMassFragmentAccess::ReadOnly);
}

void UMovementProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    MovementQuery.ForEachEntityChunk(EntityManager, Context, [this](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TArrayView<FTransformFragment> Transforms = Context.GetMutableFragmentView<FTransformFragment>();
        TArrayView<FMovementFragment> Movements = Context.GetMutableFragmentView<FMovementFragment>();
        TArrayView<FNavigationFragment> Navigations = Context.GetMutableFragmentView<FNavigationFragment>();
        TConstArrayView<FAvoidanceFragment> Avoidances = Context.GetFragmentView<FAvoidanceFragment>();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            FTransformFragment& Transform = Transforms[EntityIndex];
            FMovementFragment& Movement = Movements[EntityIndex];
            FNavigationFragment& Navigation = Navigations[EntityIndex];
            const FAvoidanceFragment& Avoidance = Avoidances[EntityIndex];

            // 1. 更新路径
            UpdatePath(Navigation, Transform);

            // 2. 计算期望速度
            FVector DesiredVelocity = CalculateDesiredVelocity(Navigation, Transform);

            // 3. 计算避障力
            FVector AvoidanceForce = CalculateAvoidanceForce(Avoidance, Transform, EntityManager);

            // 4. 组合最终速度
            Movement.DesiredVelocity = DesiredVelocity + AvoidanceForce;
            Movement.DesiredVelocity = Movement.DesiredVelocity.GetClampedToMaxSize(Movement.MaxSpeed);

            // 5. 更新实际速度（物理积分）
            float DeltaTime = Context.GetDeltaTimeSeconds();
            Movement.CurrentVelocity = FMath::VInterpTo(Movement.CurrentVelocity, Movement.DesiredVelocity, DeltaTime, Movement.Acceleration);

            // 6. 更新位置
            Transform.PreviousPosition = Transform.Position;
            Transform.Position += Movement.CurrentVelocity * DeltaTime;

            // 7. 更新朝向
            if (!Movement.CurrentVelocity.IsNearlyZero())
            {
                FRotator TargetRotation = Movement.CurrentVelocity.Rotation();
                Transform.Rotation = FMath::RInterpTo(Transform.Rotation, TargetRotation, DeltaTime, Movement.TurnRate);
            }
        }
    });
}
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
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery AttackQuery;
    
    // 攻击算法
    FMassEntityHandle FindTarget(const FTransformFragment& Transform, const FAttackFragment& Attack, const FMassEntityManager& EntityManager);
    bool IsInRange(const FVector& AttackerPos, const FVector& TargetPos, float Range);
    void ExecuteAttack(FMassEntityHandle Attacker, FMassEntityHandle Target, const FAttackFragment& Attack, FMassEntityManager& EntityManager);
};

void UAttackProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    AttackQuery.ForEachEntityChunk(EntityManager, Context, [this, &EntityManager](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TConstArrayView<FTransformFragment> Transforms = Context.GetFragmentView<FTransformFragment>();
        TArrayView<FAttackFragment> Attacks = Context.GetMutableFragmentView<FAttackFragment>();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();

        float CurrentTime = Context.GetWorld()->GetTimeSeconds();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            const FTransformFragment& Transform = Transforms[EntityIndex];
            FAttackFragment& Attack = Attacks[EntityIndex];
            FMassEntityHandle ThisEntity = Entities[EntityIndex];

            // 1. 检查攻击冷却
            if (CurrentTime - Attack.LastAttackTime < 1.0f / Attack.AttackSpeed)
            {
                continue;
            }

            // 2. 寻找目标
            if (!Attack.CurrentTarget.IsValid())
            {
                Attack.CurrentTarget = FindTarget(Transform, Attack, EntityManager);
            }

            // 3. 验证目标
            if (!Attack.CurrentTarget.IsValid())
            {
                continue;
            }

            // 4. 检查目标是否在范围内
            FMassEntityView TargetView(EntityManager, Attack.CurrentTarget);
            if (!TargetView.IsSet())
            {
                Attack.CurrentTarget.Reset();
                continue;
            }

            const FTransformFragment& TargetTransform = TargetView.GetFragmentData<FTransformFragment>();
            if (!IsInRange(Transform.Position, TargetTransform.Position, Attack.AttackRange))
            {
                continue;
            }

            // 5. 执行攻击
            ExecuteAttack(ThisEntity, Attack.CurrentTarget, Attack, EntityManager);
            Attack.LastAttackTime = CurrentTime;
        }
    });
}

void UAttackProcessor::ExecuteAttack(FMassEntityHandle Attacker, FMassEntityHandle Target, const FAttackFragment& Attack, FMassEntityManager& EntityManager)
{
    // 给目标添加伤害请求Fragment
    FDamageRequestFragment DamageRequest;
    DamageRequest.AttackerEntity = Attacker;
    DamageRequest.DamageAmount = Attack.AttackDamage;
    DamageRequest.DamageType = Attack.AttackType;
    
    EntityManager.AddFragmentToEntity(Target, DamageRequest);
    
    // 发送攻击信号
    if (UMassSignalSubsystem* SignalSubsystem = EntityManager.GetWorld().GetSubsystem<UMassSignalSubsystem>())
    {
        SignalSubsystem->SignalEntity(TEXT("OnAttackExecuted"), Attacker);
    }
}
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
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery DamageQuery;
    
    float CalculateFinalDamage(const FDamageRequestFragment& Request, const FDefenseFragment& Defense, const FMassEntityManager& EntityManager);
};

void UDamageProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    DamageQuery.ForEachEntityChunk(EntityManager, Context, [this, &EntityManager](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TConstArrayView<FDamageRequestFragment> DamageRequests = Context.GetFragmentView<FDamageRequestFragment>();
        TArrayView<FHealthFragment> Healths = Context.GetMutableFragmentView<FHealthFragment>();
        TConstArrayView<FDefenseFragment> Defenses = Context.GetFragmentView<FDefenseFragment>();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            const FDamageRequestFragment& DamageRequest = DamageRequests[EntityIndex];
            FHealthFragment& Health = Healths[EntityIndex];
            const FDefenseFragment& Defense = Defenses[EntityIndex];
            FMassEntityHandle ThisEntity = Entities[EntityIndex];

            // 1. 计算最终伤害
            float FinalDamage = CalculateFinalDamage(DamageRequest, Defense, EntityManager);

            // 2. 应用伤害
            Health.CurrentHealth = FMath::Max(0.0f, Health.CurrentHealth - FinalDamage);

            // 3. 检查死亡
            if (Health.CurrentHealth <= 0.0f && Health.bIsAlive)
            {
                Health.bIsAlive = false;
                
                // 发送死亡信号
                if (UMassSignalSubsystem* SignalSubsystem = EntityManager.GetWorld().GetSubsystem<UMassSignalSubsystem>())
                {
                    SignalSubsystem->SignalEntity(TEXT("OnEntityDeath"), ThisEntity);
                }
            }

            // 4. 移除伤害请求Fragment
            Context.Defer().RemoveFragment<FDamageRequestFragment>(ThisEntity);
        }
    });
}

float UDamageProcessor::CalculateFinalDamage(const FDamageRequestFragment& Request, const FDefenseFragment& Defense, const FMassEntityManager& EntityManager)
{
    float BaseDamage = Request.DamageAmount;
    
    // 通过句柄获取攻击者最新数据
    FMassEntityView AttackerView(EntityManager, Request.AttackerEntity);
    if (AttackerView.IsSet())
    {
        // 可以获取攻击者的buff、装备等最新数据
        // const FAttackFragment& AttackerStats = AttackerView.GetFragmentData<FAttackFragment>();
        // BaseDamage = AttackerStats.AttackDamage;  // 使用最新攻击力
    }
    
    float FinalDamage = BaseDamage;
    
    // 根据伤害类型计算防御
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
```

---

## 三、空间分区系统集成

### 3.1 空间网格处理器

```cpp
UCLASS()
class USpatialGridProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    USpatialGridProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery GridUpdateQuery;
    
    // 空间网格系统
    struct FSpatialCell
    {
        TArray<FMassEntityHandle> Entities;
        FVector2D CellCoordinate;
    };
    
    TMap<FIntPoint, FSpatialCell> SpatialGrid;
    static constexpr float CellSize = 1024.0f;  // 大格子尺寸
    
    FIntPoint WorldToGrid(const FVector& WorldPos);
    TArray<FMassEntityHandle> QueryNearbyEntities(const FVector& Center, float Radius);
    void UpdateEntityGrid(FMassEntityHandle Entity, const FVector& NewPos, const FVector& OldPos);
};

FIntPoint USpatialGridProcessor::WorldToGrid(const FVector& WorldPos)
{
    return FIntPoint(
        FMath::FloorToInt(WorldPos.X / CellSize),
        FMath::FloorToInt(WorldPos.Y / CellSize)
    );
}

TArray<FMassEntityHandle> USpatialGridProcessor::QueryNearbyEntities(const FVector& Center, float Radius)
{
    TArray<FMassEntityHandle> Result;
    
    FIntPoint CenterGrid = WorldToGrid(Center);
    int32 GridRadius = FMath::CeilToInt(Radius / CellSize);
    
    for (int32 X = CenterGrid.X - GridRadius; X <= CenterGrid.X + GridRadius; ++X)
    {
        for (int32 Y = CenterGrid.Y - GridRadius; Y <= CenterGrid.Y + GridRadius; ++Y)
        {
            FIntPoint GridPos(X, Y);
            if (FSpatialCell* Cell = SpatialGrid.Find(GridPos))
            {
                Result.Append(Cell->Entities);
            }
        }
    }
    
    return Result;
}

void USpatialGridProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    // 更新所有实体的网格位置
    GridUpdateQuery.ForEachEntityChunk(EntityManager, Context, [this](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TConstArrayView<FTransformFragment> Transforms = Context.GetFragmentView<FTransformFragment>();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            const FTransformFragment& Transform = Transforms[EntityIndex];
            FMassEntityHandle Entity = Entities[EntityIndex];
            
            UpdateEntityGrid(Entity, Transform.Position, Transform.PreviousPosition);
        }
    });
}
```

### 3.2 碰撞检测优化

```cpp
// 碰撞检测Fragment
USTRUCT()
struct FCollisionFragment : public FMassFragment
{
    GENERATED_BODY()
    
    float CollisionRadius = 50.0f;
    uint8 CollisionLayer = 0;  // 0=地面单位, 1=空中单位, 2=建筑
    uint8 CollisionMask = 0xFF;  // 与哪些层碰撞
    
    bool bBlocksMovement = true;
    bool bBlocksProjectiles = false;
};

// 碰撞处理器
UCLASS()
class UCollisionProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UCollisionProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery CollisionQuery;
    
    bool CheckCollision(const FTransformFragment& A, const FCollisionFragment& CollisionA,
                       const FTransformFragment& B, const FCollisionFragment& CollisionB);
    FVector ResolveCollision(const FTransformFragment& A, const FTransformFragment& B, float CombinedRadius);
};

bool UCollisionProcessor::CheckCollision(const FTransformFragment& A, const FCollisionFragment& CollisionA,
                                        const FTransformFragment& B, const FCollisionFragment& CollisionB)
{
    // 检查层级掩码
    if (!(CollisionA.CollisionMask & (1 << CollisionB.CollisionLayer)))
    {
        return false;
    }
    
    // 检查距离
    float CombinedRadius = CollisionA.CollisionRadius + CollisionB.CollisionRadius;
    float DistanceSquared = FVector::DistSquared(A.Position, B.Position);
    
    return DistanceSquared <= (CombinedRadius * CombinedRadius);
}

FVector UCollisionProcessor::ResolveCollision(const FTransformFragment& A, const FTransformFragment& B, float CombinedRadius)
{
    FVector Direction = (A.Position - B.Position).GetSafeNormal();
    float CurrentDistance = FVector::Dist(A.Position, B.Position);
    float PenetrationDepth = CombinedRadius - CurrentDistance;
    
    return Direction * PenetrationDepth;
}
```

---

## 四、实体通信与事件系统

### 4.1 信号系统集成

```cpp
// 信号常量定义
namespace URTSSignals
{
    static const FName OnEntityDeath = TEXT("OnEntityDeath");
    static const FName OnEntitySpawn = TEXT("OnEntitySpawn");
    static const FName OnAttackExecuted = TEXT("OnAttackExecuted");
    static const FName OnDamageReceived = TEXT("OnDamageReceived");
    static const FName OnTargetAcquired = TEXT("OnTargetAcquired");
    static const FName OnDestinationReached = TEXT("OnDestinationReached");
}

// 死亡处理器（响应死亡信号）
UCLASS()
class UDeathProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    UDeathProcessor();

protected:
    virtual void ConfigureQueries() override;
    virtual void Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context) override;

private:
    FMassEntityQuery DeathQuery;
};

UDeathProcessor::UDeathProcessor()
{
    ExecutionFlags = (int32)EProcessorExecutionFlags::All;
    
    // 注册信号监听
    UE::Mass::Processor::RegisterSignalWithCallback<UDeathProcessor>(
        *this, URTSSignals::OnEntityDeath, UDeathProcessor::StaticGetClass());
}

void UDeathProcessor::Execute(FMassEntityManager& EntityManager, FMassExecutionContext& Context)
{
    // 这个处理器只在实体死亡时执行
    DeathQuery.ForEachEntityChunk(EntityManager, Context, [this](FMassExecutionContext& Context)
    {
        const int32 NumEntities = Context.GetNumEntities();
        TConstArrayView<FTransformFragment> Transforms = Context.GetFragmentView<FTransformFragment>();
        TConstArrayView<FEntityIdFragment> EntityIds = Context.GetFragmentView<FEntityIdFragment>();
        const FMassEntityHandle* Entities = Context.GetEntities().GetData();

        for (int32 EntityIndex = 0; EntityIndex < NumEntities; ++EntityIndex)
        {
            const FTransformFragment& Transform = Transforms[EntityIndex];
            const FEntityIdFragment& EntityId = EntityIds[EntityIndex];
            FMassEntityHandle Entity = Entities[EntityIndex];

            // 1. 生成死亡特效
            // SpawnDeathEffect(Transform.Position, EntityId.EntityType);

            // 2. 掉落物品
            // SpawnLoot(Transform.Position, EntityId.EntityType);

            // 3. 更新玩家统计
            // UpdatePlayerStats(EntityId.PlayerId, EntityId.EntityType);

            // 4. 清理相关引用
            // CleanupEntityReferences(Entity);

            // 5. 销毁实体
            Context.Defer().DestroyEntity(Entity);
        }
    });
}
```

### 4.2 实体工厂系统

```cpp
// 实体工厂
UCLASS()
class UMassEntityFactory : public UObject
{
    GENERATED_BODY()

public:
    // 创建不同类型的实体
    static FMassEntityHandle CreateUnit(FMassEntityManager& EntityManager, const FVector& Position, uint8 UnitType, uint8 PlayerId);
    static FMassEntityHandle CreateHero(FMassEntityManager& EntityManager, const FVector& Position, uint8 HeroType, uint8 PlayerId);
    static FMassEntityHandle CreateBuilding(FMassEntityManager& EntityManager, const FVector& Position, uint8 BuildingType, uint8 PlayerId);
    static FMassEntityHandle CreateProjectile(FMassEntityManager& EntityManager, const FVector& StartPos, const FVector& TargetPos, uint8 ProjectileType);

private:
    // 添加通用Fragment
    static void AddBasicFragments(FMassEntityManager& EntityManager, FMassEntityHandle Entity, const FVector& Position, uint8 EntityType, uint8 PlayerId);
    static void AddCombatFragments(FMassEntityManager& EntityManager, FMassEntityHandle Entity, float Health, float Attack, float Defense);
    static void AddMovementFragments(FMassEntityManager& EntityManager, FMassEntityHandle Entity, float Speed, float TurnRate);
};

FMassEntityHandle UMassEntityFactory::CreateUnit(FMassEntityManager& EntityManager, const FVector& Position, uint8 UnitType, uint8 PlayerId)
{
    FMassEntityHandle Entity = EntityManager.CreateEntity();
    
    // 添加基础Fragment
    AddBasicFragments(EntityManager, Entity, Position, 0, PlayerId);
    
    // 添加战斗Fragment
    AddCombatFragments(EntityManager, Entity, 100.0f, 15.0f, 5.0f);
    
    // 添加移动Fragment
    AddMovementFragments(EntityManager, Entity, 300.0f, 360.0f);
    
    // 添加碰撞Fragment
    FCollisionFragment Collision;
    Collision.CollisionRadius = 25.0f;
    Collision.CollisionLayer = 0;
    EntityManager.AddFragmentToEntity(Entity, Collision);
    
    // 发送生成信号
    if (UMassSignalSubsystem* SignalSubsystem = EntityManager.GetWorld().GetSubsystem<UMassSignalSubsystem>())
    {
        SignalSubsystem->SignalEntity(URTSSignals::OnEntitySpawn, Entity);
    }
    
    return Entity;
}

void UMassEntityFactory::AddBasicFragments(FMassEntityManager& EntityManager, FMassEntityHandle Entity, const FVector& Position, uint8 EntityType, uint8 PlayerId)
{
    // 变换Fragment
    FTransformFragment Transform;
    Transform.Position = Position;
    Transform.PreviousPosition = Position;
    Transform.Rotation = FRotator::ZeroRotator;
    Transform.Scale = FVector::OneVector;
    EntityManager.AddFragmentToEntity(Entity, Transform);
    
    // ID Fragment
    FEntityIdFragment EntityId;
    EntityId.EntityId = Entity.Index;  // 使用Entity的Index作为ID
    EntityId.EntityType = EntityType;
    EntityId.PlayerId = PlayerId;
    EntityManager.AddFragmentToEntity(Entity, EntityId);
}

void UMassEntityFactory::AddCombatFragments(FMassEntityManager& EntityManager, FMassEntityHandle Entity, float Health, float Attack, float Defense)
{
    // 生命值Fragment
    FHealthFragment HealthFragment;
    HealthFragment.CurrentHealth = Health;
    HealthFragment.MaxHealth = Health;
    HealthFragment.bIsAlive = true;
    EntityManager.AddFragmentToEntity(Entity, HealthFragment);
    
    // 攻击Fragment
    FAttackFragment AttackFragment;
    AttackFragment.AttackDamage = Attack;
    AttackFragment.AttackRange = 200.0f;
    AttackFragment.AttackSpeed = 1.0f;
    EntityManager.AddFragmentToEntity(Entity, AttackFragment);
    
    // 防御Fragment
    FDefenseFragment DefenseFragment;
    DefenseFragment.Armor = Defense;
    DefenseFragment.MagicResistance = 0.0f;
    DefenseFragment.DamageReduction = 0.0f;
    EntityManager.AddFragmentToEntity(Entity, DefenseFragment);
}

void UMassEntityFactory::AddMovementFragments(FMassEntityManager& EntityManager, FMassEntityHandle Entity, float Speed, float TurnRate)
{
    // 移动Fragment
    FMovementFragment Movement;
    Movement.MaxSpeed = Speed;
    Movement.Acceleration = 1000.0f;
    Movement.TurnRate = TurnRate;
    EntityManager.AddFragmentToEntity(Entity, Movement);
    
    // 导航Fragment
    FNavigationFragment Navigation;
    Navigation.AcceptanceRadius = 50.0f;
    EntityManager.AddFragmentToEntity(Entity, Navigation);
    
    // 避障Fragment
    FAvoidanceFragment Avoidance;
    Avoidance.AvoidanceRadius = 100.0f;
    Avoidance.AvoidanceForce = 500.0f;
    EntityManager.AddFragmentToEntity(Entity, Avoidance);
}
```

---

## 五、调试与可视化工具

### 5.1 Mass调试器

```cpp
// Mass调试器组件
UCLASS()
class UMassDebugger : public UActorComponent
{
    GENERATED_BODY()

public:
    UMassDebugger();

    // 调试功能
    UFUNCTION(CallInEditor = true, Category = "Mass Debug")
    void ShowAllEntities();
    
    UFUNCTION(CallInEditor = true, Category = "Mass Debug")
    void ShowEntityDetails(int32 EntityId);
    
    UFUNCTION(CallInEditor = true, Category = "Mass Debug")
    void ShowSpatialGrid();
    
    UFUNCTION(CallInEditor = true, Category = "Mass Debug")
    void ShowProcessorPerformance();

protected:
    virtual void BeginPlay() override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
    // 调试数据
    TArray<FMassEntityHandle> AllEntities;
    TMap<FMassEntityHandle, FString> EntityDebugInfo;
    
    // 可视化
    void DrawEntityInfo(const FMassEntityHandle& Entity, const FVector& Position);
    void DrawSpatialGridCell(const FIntPoint& GridPos, const FVector& WorldPos);
    void DrawConnectionLines(const FMassEntityHandle& Entity);
    
    // 性能统计
    struct FProcessorStats
    {
        FString ProcessorName;
        float AverageExecutionTime;
        int32 EntitiesProcessed;
        float MemoryUsage;
    };
    
    TArray<FProcessorStats> ProcessorStatistics;
};

void UMassDebugger::ShowAllEntities()
{
    if (UMassEntitySubsystem* EntitySubsystem = GetWorld()->GetSubsystem<UMassEntitySubsystem>())
    {
        FMassEntityManager& EntityManager = EntitySubsystem->GetEntityManager();
        
        // 清空现有数据
        AllEntities.Empty();
        EntityDebugInfo.Empty();
        
        // 遍历所有实体
        EntityManager.ForEachEntity([this](FMassEntityHandle Entity)
        {
            AllEntities.Add(Entity);
            
            // 收集实体信息
            FString DebugInfo = FString::Printf(TEXT("Entity %d: "), Entity.Index);
            
            FMassEntityView EntityView(EntityManager, Entity);
            if (EntityView.IsSet())
            {
                // 检查各种Fragment
                if (EntityView.HasFragment<FTransformFragment>())
                {
                    const FTransformFragment& Transform = EntityView.GetFragmentData<FTransformFragment>();
                    DebugInfo += FString::Printf(TEXT("Pos(%.1f,%.1f,%.1f) "), Transform.Position.X, Transform.Position.Y, Transform.Position.Z);
                }
                
                if (EntityView.HasFragment<FHealthFragment>())
                {
                    const FHealthFragment& Health = EntityView.GetFragmentData<FHealthFragment>();
                    DebugInfo += FString::Printf(TEXT("HP(%.1f/%.1f) "), Health.CurrentHealth, Health.MaxHealth);
                }
                
                if (EntityView.HasFragment<FEntityIdFragment>())
                {
                    const FEntityIdFragment& EntityId = EntityView.GetFragmentData<FEntityIdFragment>();
                    DebugInfo += FString::Printf(TEXT("Type(%d) Player(%d) "), EntityId.EntityType, EntityId.PlayerId);
                }
            }
            
            EntityDebugInfo.Add(Entity, DebugInfo);
        });
        
        UE_LOG(LogTemp, Warning, TEXT("Found %d entities"), AllEntities.Num());
    }
}

void UMassDebugger::DrawEntityInfo(const FMassEntityHandle& Entity, const FVector& Position)
{
    // 绘制实体信息
    if (FString* DebugInfo = EntityDebugInfo.Find(Entity))
    {
        // 在世界空间显示文本
        DrawDebugString(GetWorld(), Position + FVector(0, 0, 100), *DebugInfo, nullptr, FColor::White, 0.0f);
    }
    
    // 绘制实体边界
    DrawDebugSphere(GetWorld(), Position, 50.0f, 12, FColor::Green, false, 0.0f);
}
```

### 5.2 性能监控工具

```cpp
// 性能监控器
UCLASS()
class UMassPerformanceMonitor : public UGameInstanceSubsystem
{
    GENERATED_BODY()

public:
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;

    // 性能统计
    void RecordProcessorExecution(const FString& ProcessorName, float ExecutionTime, int32 EntitiesProcessed);
    void RecordMemoryUsage(const FString& Category, float MemoryMB);
    void RecordFrameTime(float FrameTime);

    // 获取统计数据
    TArray<FProcessorPerformanceData> GetProcessorStats() const;
    FMemoryUsageData GetMemoryStats() const;
    FFrameTimeData GetFrameTimeStats() const;

private:
    // 性能数据结构
    struct FProcessorPerformanceData
    {
        FString ProcessorName;
        float TotalExecutionTime;
        float AverageExecutionTime;
        int32 ExecutionCount;
        int32 TotalEntitiesProcessed;
        float EntitiesPerSecond;
    };
    
    struct FMemoryUsageData
    {
        float TotalMemoryMB;
        float FragmentMemoryMB;
        float ProcessorMemoryMB;
        float EntityMemoryMB;
    };
    
    struct FFrameTimeData
    {
        float AverageFrameTime;
        float MinFrameTime;
        float MaxFrameTime;
        float FrameTimeVariance;
    };
    
    // 统计数据
    TMap<FString, FProcessorPerformanceData> ProcessorStats;
    FMemoryUsageData MemoryStats;
    
    // 帧时间统计
    TArray<float> FrameTimeHistory;
    static constexpr int32 MaxFrameTimeHistory = 300; // 5秒历史（60fps）
    
    // 定时器
    FTimerHandle StatsUpdateTimer;
    void UpdateStats();
};

void UMassPerformanceMonitor::RecordProcessorExecution(const FString& ProcessorName, float ExecutionTime, int32 EntitiesProcessed)
{
    FProcessorPerformanceData& Data = ProcessorStats.FindOrAdd(ProcessorName);
    Data.ProcessorName = ProcessorName;
    Data.TotalExecutionTime += ExecutionTime;
    Data.ExecutionCount++;
    Data.TotalEntitiesProcessed += EntitiesProcessed;
    
    // 计算平均值
    Data.AverageExecutionTime = Data.TotalExecutionTime / Data.ExecutionCount;
    Data.EntitiesPerSecond = Data.TotalEntitiesProcessed / Data.TotalExecutionTime;
}

void UMassPerformanceMonitor::UpdateStats()
{
    // 更新内存统计
    if (UMassEntitySubsystem* EntitySubsystem = GetGameInstance()->GetWorld()->GetSubsystem<UMassEntitySubsystem>())
    {
        FMassEntityManager& EntityManager = EntitySubsystem->GetEntityManager();
        
        // 获取Fragment内存使用
        // MemoryStats.FragmentMemoryMB = EntityManager.GetFragmentMemoryUsage() / (1024.0f * 1024.0f);
        
        // 获取实体数量
        int32 EntityCount = EntityManager.GetNumEntities();
        MemoryStats.EntityMemoryMB = EntityCount * sizeof(FMassEntityHandle) / (1024.0f * 1024.0f);
    }
    
    // 清理过时的统计数据
    const float CurrentTime = FPlatformTime::Seconds();
    for (auto It = ProcessorStats.CreateIterator(); It; ++It)
    {
        // 如果处理器超过10秒没有执行，清理其统计数据
        // if (CurrentTime - It.Value().LastExecutionTime > 10.0f)
        // {
        //     It.RemoveCurrent();
        // }
    }
}
```

---

## 六、实施建议

### 6.1 开发优先级

1. **第一周**：实现基础Fragment体系和简单的移动处理器
2. **第二周**：添加攻击和伤害系统
3. **第三周**：集成空间分区和碰撞检测
4. **第四周**：实现信号系统和实体工厂
5. **第五周**：开发调试工具和性能监控
6. **第六周**：优化和测试

### 6.2 测试策略

```cpp
// 单元测试示例
UCLASS()
class UMassSystemTest : public UObject
{
    GENERATED_BODY()

public:
    // 测试实体创建
    UFUNCTION(CallInEditor = true, Category = "Mass Test")
    void TestEntityCreation();
    
    // 测试移动系统
    UFUNCTION(CallInEditor = true, Category = "Mass Test")
    void TestMovementSystem();
    
    // 测试战斗系统
    UFUNCTION(CallInEditor = true, Category = "Mass Test")
    void TestCombatSystem();
    
    // 性能测试
    UFUNCTION(CallInEditor = true, Category = "Mass Test")
    void TestPerformanceWithMultipleEntities();
};

void UMassSystemTest::TestEntityCreation()
{
    if (UMassEntitySubsystem* EntitySubsystem = GetWorld()->GetSubsystem<UMassEntitySubsystem>())
    {
        FMassEntityManager& EntityManager = EntitySubsystem->GetEntityManager();
        
        // 创建1000个实体
        TArray<FMassEntityHandle> TestEntities;
        for (int32 i = 0; i < 1000; ++i)
        {
            FVector RandomPos = FVector(
                FMath::RandRange(-5000.0f, 5000.0f),
                FMath::RandRange(-5000.0f, 5000.0f),
                0.0f
            );
            
            FMassEntityHandle Entity = UMassEntityFactory::CreateUnit(EntityManager, RandomPos, 0, 0);
            TestEntities.Add(Entity);
        }
        
        UE_LOG(LogTemp, Warning, TEXT("Created %d test entities"), TestEntities.Num());
        
        // 验证实体数量
        int32 ActualEntityCount = EntityManager.GetNumEntities();
        check(ActualEntityCount >= 1000);
    }
}
```

### 6.3 性能基准

- **目标**：200个实体稳定60FPS
- **内存使用**：每个实体平均300字节
- **处理器性能**：单个处理器执行时间<2ms
- **空间查询**：半径查询<0.5ms

这套实现指南为纯Mass架构提供了详细的代码实现方案，确保开发团队能够按照统一的标准构建高性能的RTS游戏系统。

---

**文档版本**：v1.0  
**最后更新**：2025年1月17日  
**维护者**：Claude AI Assistant  
**适用阶段**：开发第一阶段