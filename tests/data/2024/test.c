#define pr_fmt(fmt) "kallsyms_selftest: " fmt

#include <linux/init.h>
#include <linux/module.h>
#include <linux/kallsyms.h>
#include <linux/random.h>
#include <linux/sched/clock.h>
#include <linux/kthread.h>
#include <linux/vmalloc.h>

#include "kallsyms_internal.h"
#include "kallsyms_selftest.h"


#define MAX_NUM_OF_RECORDS		64

struct rcu_test_struct2 {
	struct maple_tree *mt;
	unsigned long index[RCU_RANGE_COUNT];
	unsigned long last[RCU_RANGE_COUNT];
};
static void test_perf_kallsyms_on_each_match_symbol(void)
{
	u64 t0, t1;
	struct test_stat stat;
	memset(&stat, 0, sizeof(stat));
	stat.max = INT_MAX;
	stat.name = stub_name;
	t0 = ktime_get_ns();
	kallsyms_on_each_match_symbol(match_symbol, stat.name, &stat);
	t1 = ktime_get_ns();
	pr_info("kallsyms_on_each_match_symbol() traverse all: %lld ns\n", t1 - t0);
}
static int
get_alloc_node_count(struct ma_state *mas)
{
	int count = 1;
	struct maple_alloc *node = mas->alloc;
	if (!node || ((unsigned long)node & 0x1))
		return 0;
	while (node->node_count) {
		count += node->node_count;
		node = node->slot[0];
	}
	return count;
}
void __init
wildfire_init_arch(void)
{
	int qbbno;

	__direct_map_base = 0x40000000UL;
	__direct_map_size = 0x80000000UL;
}
