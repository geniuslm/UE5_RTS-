# UE5 RTS 空间分区系统设计方案

## 概述

本文档详细设计了替代Chaos物理引擎的高性能空间分区系统，专为RTS游戏的大规模单位管理优化。基于讨论中的核心理念：**扩展而非新建**，将2D网格系统与Mass框架完美结合。

## 核心设计理念

### 避免"万物皆实体"陷阱
```cpp
// 错误做法：把格子做成Mass实体
// 这会导致实体数量爆炸：64x64 = 4096个格子实体
struct FGridCellEntity {}; // ❌ 错误！

// 正确做法：扩展现有2D网格系统
// 格子是数据结构，不是实体
struct FGridCell {}; // ✅ 正确！
```

### 数据驱动的空间管理
- **Mass实体世界**：管理动态单位
- **自定义子系统**：管理静态空间结构  
- **处理器胶水**：连接两个世界

## 一、系统架构设计

### 1.1 分层网格结构

#### 双层网格系统（基于讨论优化）
```cpp
// 空间分区配置 - 专为2D RTS优化
struct FSpatialPartitionConfig
{
    // 大格子配置（粗略查询，激活模式优化）
    static constexpr int32 LARGE_GRID_SIZE = 1024;    // 1024cm = 10.24m
    static constexpr int32 LARGE_GRID_SHIFT = 10;     // 2^10 = 1024，位运算优化
    
    // 小格子配置（精确查询，空间分区优化）
    static constexpr int32 SMALL_GRID_SIZE = 32;      // 32cm = 0.32m
    static constexpr int32 SMALL_GRID_SHIFT = 5;      // 2^5 = 32，位运算优化
    
    // 世界边界（2D专用）
    static constexpr int32 WORLD_SIZE = 65536;        // 655.36m x 655.36m
    static constexpr int32 WORLD_HALF_SIZE = WORLD_SIZE / 2;
    
    // 网格数量（2D优化，避免3D的Z轴浪费）
    static constexpr int32 LARGE_GRID_COUNT = WORLD_SIZE / LARGE_GRID_SIZE;  // 64x64 = 4096
    static constexpr int32 SMALL_GRID_COUNT = WORLD_SIZE / SMALL_GRID_SIZE;  // 2048x2048 = 4M
    
    // 性能优化常量
    static constexpr int32 MAX_ENTITIES_PER_LARGE_CELL = 64;  // 激活模式优化
    static constexpr int32 MAX_ENTITIES_PER_SMALL_CELL = 8;   // 缓存友好大小
    static constexpr float GRID_TO_WORLD_SCALE = 1.0f / 100.0f;  // cm到m转换
};
```

#### 网格单元设计
```cpp
// 大格子单元（粗略查询）
struct FLargeGridCell
{
    // 该格子内的所有实体（使用紧凑数组）
    TArray<FMassEntityHandle> Entities;
    
    // 快速查询缓存
    uint32 EntityCount;
    uint32 LastUpdateFrame;
    
    // 邻居格子缓存（9个格子：自己+8个邻居）
    TStaticArray<FLargeGridCell*, 9> NeighborCells;
    
    // 预分配内存管理
    void Reserve(int32 Capacity) { Entities.Reserve(Capacity); }
    void Reset() { Entities.Reset(); EntityCount = 0; }
    
    // 内存占用：基础48字节 + 动态数组
};

// 小格子单元（精确查询）
struct FSmallGridCell
{
    // 使用位集合标记实体存在（针对密集场景优化）
    TBitArray<> EntityPresence;
    
    // 实体索引映射
    TMap<FMassEntityHandle, int32> EntityIndices;
    
    // 碰撞检测优化数据
    uint32 CollisionMask;          // 碰撞类型掩码
    uint16 DynamicEntityCount;     // 动态实体数量
    uint16 StaticEntityCount;      // 静态实体数量
    
    // 内存占用：约64字节 + 动态数据
};
```

### 1.2 坐标转换系统

#### 高效的位运算转换
```cpp
// 空间坐标转换工具
class FSpatialCoordinateConverter
{
public:
    // 世界坐标转大格子坐标
    static FIntPoint WorldToLargeGrid(const FVector& WorldPos)
    {
        const int32 X = (static_cast<int32>(WorldPos.X) + FSpatialPartitionConfig::WORLD_HALF_SIZE) 
                       >> FSpatialPartitionConfig::LARGE_GRID_SHIFT;
        const int32 Y = (static_cast<int32>(WorldPos.Y) + FSpatialPartitionConfig::WORLD_HALF_SIZE) 
                       >> FSpatialPartitionConfig::LARGE_GRID_SHIFT;
        return FIntPoint(X, Y);
    }
    
    // 世界坐标转小格子坐标
    static FIntPoint WorldToSmallGrid(const FVector& WorldPos)
    {
        const int32 X = (static_cast<int32>(WorldPos.X) + FSpatialPartitionConfig::WORLD_HALF_SIZE) 
                       >> FSpatialPartitionConfig::SMALL_GRID_SHIFT;
        const int32 Y = (static_cast<int32>(WorldPos.Y) + FSpatialPartitionConfig::WORLD_HALF_SIZE) 
                       >> FSpatialPartitionConfig::SMALL_GRID_SHIFT;
        return FIntPoint(X, Y);
    }
    
    // 大格子坐标转世界坐标
    static FVector LargeGridToWorld(const FIntPoint& GridPos)
    {
        const float X = (GridPos.X << FSpatialPartitionConfig::LARGE_GRID_SHIFT) 
                       - FSpatialPartitionConfig::WORLD_HALF_SIZE;
        const float Y = (GridPos.Y << FSpatialPartitionConfig::LARGE_GRID_SHIFT) 
                       - FSpatialPartitionConfig::WORLD_HALF_SIZE;
        return FVector(X, Y, 0.0f);
    }
    
    // 验证坐标有效性
    static bool IsValidGridCoordinate(const FIntPoint& GridPos, bool bIsLargeGrid)
    {
        const int32 MaxCoord = bIsLargeGrid ? 
            FSpatialPartitionConfig::LARGE_GRID_COUNT : 
            FSpatialPartitionConfig::SMALL_GRID_COUNT;
        return GridPos.X >= 0 && GridPos.X < MaxCoord && 
               GridPos.Y >= 0 && GridPos.Y < MaxCoord;
    }
};
```

### 1.3 核心分区管理器

#### 空间分区子系统
```cpp
UCLASS()
class RTSGAME_API USpatialPartitionSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    // 子系统初始化
    virtual void Initialize(FSubsystemCollectionBase& Collection) override;
    virtual void Deinitialize() override;
    
    // 实体管理
    void RegisterEntity(FMassEntityHandle Entity, const FVector& Location, float Radius);
    void UnregisterEntity(FMassEntityHandle Entity);
    void UpdateEntityLocation(FMassEntityHandle Entity, const FVector& NewLocation);
    
    // 空间查询接口
    void QueryEntitiesInSphere(const FVector& Center, float Radius, 
                              TArray<FMassEntityHandle>& OutEntities) const;
    void QueryEntitiesInBox(const FBox& Box, 
                           TArray<FMassEntityHandle>& OutEntities) const;
    void QueryEntitiesInCone(const FVector& Origin, const FVector& Direction, 
                            float Range, float Angle, 
                            TArray<FMassEntityHandle>& OutEntities) const;
    
    // 碰撞检测
    bool LineTrace(const FVector& Start, const FVector& End, 
                   FMassEntityHandle& OutHitEntity, FVector& OutHitLocation) const;
    bool SphereOverlap(const FVector& Center, float Radius, 
                      TArray<FMassEntityHandle>& OutOverlappingEntities) const;

private:
    // 网格存储
    TArray<FLargeGridCell> LargeGridCells;
    TArray<FSmallGridCell> SmallGridCells;
    
    // 实体位置缓存
    TMap<FMassEntityHandle, FVector> EntityLocations;
    TMap<FMassEntityHandle, float> EntityRadii;
    
    // 性能统计
    mutable int32 QueryCount;
    mutable int32 HitCount;
    mutable double TotalQueryTime;
    
    // 内部工具方法
    int32 GetLargeGridIndex(const FIntPoint& GridPos) const;
    int32 GetSmallGridIndex(const FIntPoint& GridPos) const;
    void GetNeighborCells(const FIntPoint& GridPos, bool bIsLargeGrid, 
                         TArray<int32>& OutCellIndices) const;
    
    // 查询优化
    void QueryLargeGridCells(const FVector& Center, float Radius, 
                           TArray<int32>& OutCellIndices) const;
    void QuerySmallGridCells(const FVector& Center, float Radius, 
                            TArray<int32>& OutCellIndices) const;
};
```

## 二、查询算法实现

### 2.1 球形范围查询

#### 优化的球形查询算法
```cpp
void USpatialPartitionSubsystem::QueryEntitiesInSphere(const FVector& Center, float Radius, 
                                                      TArray<FMassEntityHandle>& OutEntities) const
{
    SCOPE_CYCLE_COUNTER(STAT_SpatialQuery_Sphere);
    
    OutEntities.Reset();
    
    // 步骤1：确定查询范围涉及的大格子
    TArray<int32> RelevantLargeCells;
    QueryLargeGridCells(Center, Radius, RelevantLargeCells);
    
    // 步骤2：粗略筛选 - 在大格子中查找候选实体
    TArray<FMassEntityHandle> CandidateEntities;
    for (int32 CellIndex : RelevantLargeCells)
    {
        const FLargeGridCell& Cell = LargeGridCells[CellIndex];
        CandidateEntities.Append(Cell.Entities);
    }
    
    // 步骤3：精确检测 - 验证每个候选实体是否在球形范围内
    const float RadiusSquared = Radius * Radius;
    for (const FMassEntityHandle& Entity : CandidateEntities)
    {
        const FVector* EntityLocation = EntityLocations.Find(Entity);
        if (EntityLocation)
        {
            const float DistanceSquared = FVector::DistSquared(Center, *EntityLocation);
            if (DistanceSquared <= RadiusSquared)
            {
                OutEntities.Add(Entity);
            }
        }
    }
    
    // 性能统计
    QueryCount++;
    HitCount += OutEntities.Num();
}
```

### 2.2 扇形范围查询

#### 扇形查询算法（技能范围）
```cpp
void USpatialPartitionSubsystem::QueryEntitiesInCone(const FVector& Origin, 
                                                    const FVector& Direction, 
                                                    float Range, float Angle, 
                                                    TArray<FMassEntityHandle>& OutEntities) const
{
    SCOPE_CYCLE_COUNTER(STAT_SpatialQuery_Cone);
    
    OutEntities.Reset();
    
    // 预计算扇形参数
    const FVector NormalizedDirection = Direction.GetSafeNormal();
    const float CosHalfAngle = FMath::Cos(FMath::DegreesToRadians(Angle * 0.5f));
    const float RangeSquared = Range * Range;
    
    // 首先进行球形查询获取候选实体
    TArray<FMassEntityHandle> CandidateEntities;
    QueryEntitiesInSphere(Origin, Range, CandidateEntities);
    
    // 扇形过滤
    for (const FMassEntityHandle& Entity : CandidateEntities)
    {
        const FVector* EntityLocation = EntityLocations.Find(Entity);
        if (EntityLocation)
        {
            const FVector ToEntity = *EntityLocation - Origin;
            const float DistanceSquared = ToEntity.SizeSquared();
            
            // 距离检查
            if (DistanceSquared <= RangeSquared)
            {
                // 角度检查
                const FVector ToEntityNormalized = ToEntity.GetSafeNormal();
                const float CosAngleToEntity = FVector::DotProduct(NormalizedDirection, ToEntityNormalized);
                
                if (CosAngleToEntity >= CosHalfAngle)
                {
                    OutEntities.Add(Entity);
                }
            }
        }
    }
}
```

### 2.3 线性轨迹查询

#### 射线碰撞检测
```cpp
bool USpatialPartitionSubsystem::LineTrace(const FVector& Start, const FVector& End, 
                                          FMassEntityHandle& OutHitEntity, 
                                          FVector& OutHitLocation) const
{
    SCOPE_CYCLE_COUNTER(STAT_SpatialQuery_LineTrace);
    
    // 使用DDA算法遍历射线经过的格子
    TArray<FIntPoint> TraversedCells;
    CalculateTraversedCells(Start, End, TraversedCells);
    
    float ClosestDistance = FLT_MAX;
    bool bHit = false;
    
    // 检查每个格子中的实体
    for (const FIntPoint& CellPos : TraversedCells)
    {
        const int32 CellIndex = GetSmallGridIndex(CellPos);
        if (CellIndex >= 0 && CellIndex < SmallGridCells.Num())
        {
            const FSmallGridCell& Cell = SmallGridCells[CellIndex];
            
            // 检查格子中的每个实体
            for (const auto& EntityPair : Cell.EntityIndices)
            {
                const FMassEntityHandle& Entity = EntityPair.Key;
                const FVector* EntityLocation = EntityLocations.Find(Entity);
                const float* EntityRadius = EntityRadii.Find(Entity);
                
                if (EntityLocation && EntityRadius)
                {
                    // 射线与球体相交测试
                    FVector ClosestPoint;
                    float Distance;
                    if (LineToSphereIntersection(Start, End, *EntityLocation, *EntityRadius, 
                                                ClosestPoint, Distance))
                    {
                        if (Distance < ClosestDistance)
                        {
                            ClosestDistance = Distance;
                            OutHitEntity = Entity;
                            OutHitLocation = ClosestPoint;
                            bHit = true;
                        }
                    }
                }
            }
        }
    }
    
    return bHit;
}

// DDA算法计算射线经过的格子
void USpatialPartitionSubsystem::CalculateTraversedCells(const FVector& Start, 
                                                        const FVector& End, 
                                                        TArray<FIntPoint>& OutCells) const
{
    const FIntPoint StartGrid = FSpatialCoordinateConverter::WorldToSmallGrid(Start);
    const FIntPoint EndGrid = FSpatialCoordinateConverter::WorldToSmallGrid(End);
    
    // 实现DDA算法
    int32 X = StartGrid.X;
    int32 Y = StartGrid.Y;
    
    const int32 DeltaX = FMath::Abs(EndGrid.X - StartGrid.X);
    const int32 DeltaY = FMath::Abs(EndGrid.Y - StartGrid.Y);
    
    const int32 StepX = (StartGrid.X < EndGrid.X) ? 1 : -1;
    const int32 StepY = (StartGrid.Y < EndGrid.Y) ? 1 : -1;
    
    int32 Error = DeltaX - DeltaY;
    
    while (true)
    {
        // 添加当前格子
        if (FSpatialCoordinateConverter::IsValidGridCoordinate(FIntPoint(X, Y), false))
        {
            OutCells.Add(FIntPoint(X, Y));
        }
        
        // 到达终点
        if (X == EndGrid.X && Y == EndGrid.Y)
            break;
        
        // DDA步进
        const int32 Error2 = Error * 2;
        if (Error2 > -DeltaY)
        {
            Error -= DeltaY;
            X += StepX;
        }
        if (Error2 < DeltaX)
        {
            Error += DeltaX;
            Y += StepY;
        }
    }
}
```

## 三、性能优化策略

### 3.1 内存管理优化

#### 预分配内存池
```cpp
class FSpatialPartitionMemoryManager
{
public:
    // 实体数组对象池
    class FEntityArrayPool
    {
    public:
        TArray<FMassEntityHandle>* Acquire();
        void Release(TArray<FMassEntityHandle>* Array);
        
    private:
        TArray<TUniquePtr<TArray<FMassEntityHandle>>> Pool;
        TArray<TArray<FMassEntityHandle>*> FreeArrays;
        FCriticalSection PoolMutex;
    };
    
    // 查询结果缓存
    class FQueryResultCache
    {
    public:
        struct FCacheEntry
        {
            FVector QueryCenter;
            float QueryRadius;
            uint32 QueryFrame;
            TArray<FMassEntityHandle> Results;
        };
        
        bool TryGetCachedResult(const FVector& Center, float Radius, 
                               TArray<FMassEntityHandle>& OutResults) const;
        void CacheResult(const FVector& Center, float Radius, 
                        const TArray<FMassEntityHandle>& Results);
        
    private:
        mutable TMap<uint32, FCacheEntry> Cache;
        mutable FCriticalSection CacheMutex;
        uint32 CurrentFrame;
    };
    
    static FEntityArrayPool& GetEntityArrayPool() { return EntityArrayPool; }
    static FQueryResultCache& GetQueryCache() { return QueryCache; }
    
private:
    static FEntityArrayPool EntityArrayPool;
    static FQueryResultCache QueryCache;
};
```

### 3.2 多线程查询优化

#### 并行查询实现
```cpp
class FParallelSpatialQuery
{
public:
    // 并行球形查询
    static void ParallelQuerySphere(const USpatialPartitionSubsystem* Subsystem,
                                   const TArray<FSphereQuery>& Queries,
                                   TArray<TArray<FMassEntityHandle>>& OutResults)
    {
        OutResults.SetNum(Queries.Num());
        
        // 使用TaskGraph进行并行处理
        ParallelFor(Queries.Num(), [&](int32 Index)
        {
            const FSphereQuery& Query = Queries[Index];
            Subsystem->QueryEntitiesInSphere(Query.Center, Query.Radius, OutResults[Index]);
        });
    }
    
    // 批量查询优化
    static void BatchQuery(const USpatialPartitionSubsystem* Subsystem,
                          const TArray<FBatchQueryRequest>& Requests,
                          TArray<FBatchQueryResult>& OutResults)
    {
        // 按查询类型分组
        TArray<FSphereQuery> SphereQueries;
        TArray<FBoxQuery> BoxQueries;
        TArray<FConeQuery> ConeQueries;
        
        GroupQueriesByType(Requests, SphereQueries, BoxQueries, ConeQueries);
        
        // 并行处理每种类型的查询
        TArray<TArray<FMassEntityHandle>> SphereResults;
        TArray<TArray<FMassEntityHandle>> BoxResults;
        TArray<TArray<FMassEntityHandle>> ConeResults;
        
        ParallelInvoke(
            [&] { ParallelQuerySphere(Subsystem, SphereQueries, SphereResults); },
            [&] { ParallelQueryBox(Subsystem, BoxQueries, BoxResults); },
            [&] { ParallelQueryCone(Subsystem, ConeQueries, ConeResults); }
        );
        
        // 合并结果
        MergeResults(Requests, SphereResults, BoxResults, ConeResults, OutResults);
    }
};
```

### 3.3 缓存优化策略

#### 智能缓存系统
```cpp
class FSpatialQueryCacheManager
{
public:
    // 缓存策略配置
    struct FCacheConfig
    {
        float CacheRadius = 100.0f;        // 缓存半径阈值
        int32 MaxCacheEntries = 1000;      // 最大缓存条目数
        float CacheValidTime = 0.1f;       // 缓存有效时间（秒）
        bool bEnableTemporalCache = true;  // 启用时间缓存
        bool bEnableSpatialCache = true;   // 启用空间缓存
    };
    
    // 缓存查询结果
    void CacheQueryResult(const FVector& Center, float Radius, uint32 QueryType,
                         const TArray<FMassEntityHandle>& Results);
    
    // 尝试获取缓存结果
    bool TryGetCachedResult(const FVector& Center, float Radius, uint32 QueryType,
                           TArray<FMassEntityHandle>& OutResults) const;
    
    // 缓存失效处理
    void InvalidateCacheInRegion(const FBox& Region);
    void InvalidateCacheForEntity(FMassEntityHandle Entity);
    
    // 缓存统计
    struct FCacheStats
    {
        int32 TotalQueries;
        int32 CacheHits;
        int32 CacheMisses;
        float HitRate;
    };
    
    FCacheStats GetCacheStats() const;
    
private:
    FCacheConfig Config;
    TMap<uint64, FCacheEntry> SpatialCache;
    TMap<FMassEntityHandle, TArray<uint64>> EntityToCacheMap;
    mutable FCriticalSection CacheMutex;
    
    uint64 GenerateCacheKey(const FVector& Center, float Radius, uint32 QueryType) const;
    bool IsCacheEntryValid(const FCacheEntry& Entry) const;
};
```

## 四、与Mass系统集成

### 4.1 Mass Processor集成

#### 空间分区更新处理器
```cpp
UCLASS()
class USpatialPartitionUpdateProcessor : public UMassProcessor
{
    GENERATED_BODY()

public:
    USpatialPartitionUpdateProcessor()
    {
        ExecutionFlags = (int32)EProcessorExecutionFlags::All;
        ProcessingPhase = EMassProcessingPhase::PrePhysics;
    }

protected:
    virtual void ConfigureQueries() override
    {
        // 需要位置和空间分区Fragment的实体
        EntityQuery.AddRequirement<FRTSTransformFragment>(EMassFragmentAccess::ReadOnly);
        EntityQuery.AddRequirement<FSpatialPartitionFragment>(EMassFragmentAccess::ReadWrite);
    }
    
    virtual void Execute(FMassEntityManager& EntityManager, 
                        FMassExecutionContext& Context) override
    {
        USpatialPartitionSubsystem* SpatialSubsystem = 
            Context.GetWorld()->GetSubsystem<USpatialPartitionSubsystem>();
        
        if (!SpatialSubsystem)
            return;
        
        // 更新实体在空间分区中的位置
        EntityQuery.ForEachEntityChunk(EntityManager, Context,
            [&](FMassExecutionContext& Context)
            {
                const TArrayView<FRTSTransformFragment> Transforms = 
                    Context.GetFragmentView<FRTSTransformFragment>();
                const TArrayView<FSpatialPartitionFragment> SpatialFragments = 
                    Context.GetMutableFragmentView<FSpatialPartitionFragment>();
                
                for (int32 i = 0; i < Context.GetNumEntities(); ++i)
                {
                    const FVector& CurrentLocation = Transforms[i].Location;
                    FSpatialPartitionFragment& SpatialFragment = SpatialFragments[i];
                    
                    // 检查位置是否发生变化
                    if (!SpatialFragment.LastLocation.Equals(CurrentLocation, 1.0f))
                    {
                        // 更新空间分区
                        SpatialSubsystem->UpdateEntityLocation(
                            Context.GetEntity(i), CurrentLocation);
                        
                        // 更新缓存的位置
                        SpatialFragment.LastLocation = CurrentLocation;
                        SpatialFragment.LastUpdateFrame = Context.GetCurrentFrame();
                    }
                }
            });
    }
};
```

### 4.2 专用Fragment设计

#### 空间分区Fragment
```cpp
USTRUCT()
struct FSpatialPartitionFragment : public FMassFragment
{
    GENERATED_BODY()
    
    // 缓存的位置信息
    FVector LastLocation = FVector::ZeroVector;
    
    // 实体半径（用于碰撞检测）
    float CollisionRadius = 50.0f;
    
    // 空间分区类型
    uint8 PartitionType = 0;  // 0=动态, 1=静态, 2=大型
    
    // 最后更新帧
    uint32 LastUpdateFrame = 0;
    
    // 网格坐标缓存
    FIntPoint LargeGridCoord = FIntPoint::ZeroValue;
    FIntPoint SmallGridCoord = FIntPoint::ZeroValue;
    
    // 查询优化标志
    uint32 QueryFlags = 0;  // 位标记：可攻击、可选择、阻挡移动等
};
```

---

**文档版本**：v1.0  
**最后更新**：2025年1月17日  
**维护者**：Claude AI Assistant  
**状态**：设计完成，待实现验证