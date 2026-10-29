/* seekdb <-> hipVS bridge: plain-C CAGRA kNN; all cuVS/ROCm deps live here. */
#include "seekdb_cuvs_bridge.h"
#include <cuvs/core/c_api.h>
#include <cuvs/neighbors/cagra.h>
#include <dlpack/dlpack.h>
#ifdef __HIP_PLATFORM_AMD__
#include <cuvs/cuda_runtime.h>
#else
#include <cuda_runtime.h>
#endif
#include <stdio.h>
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

typedef struct {
  cuvsResources_t        res;
  cuvsCagraIndexParams_t ip;
  cuvsCagraIndex_t       idx;
  long n, dim;
  float* scratch_query;
  unsigned int* scratch_ids;
  float* scratch_dist;
  size_t scratch_query_bytes;
  size_t scratch_ids_bytes;
  size_t scratch_result_bytes;
  pthread_mutex_t scratch_mu;
  int scratch_mu_ready;
} sk_cuvs_index;

static int sk_size_mul(size_t left, size_t right, size_t *result)
{
  if (right != 0 && left > SIZE_MAX / right) return 0;
  *result = left * right;
  return 1;
}

void* seekdb_cuvs_build(const float* base, long n, long dim)
{
  sk_cuvs_index* h = (sk_cuvs_index*)calloc(1, sizeof(*h));
  if (!h) return NULL;
  if (cuvsResourcesCreate(&h->res) != CUVS_SUCCESS) { free(h); return NULL; }

  DLManagedTensor dset;
  long ds[2] = {n, dim};
  size_t base_elements = 0;
  size_t base_bytes = 0;
  if (base == NULL || n <= 0 || (uint64_t)n > UINT32_MAX || dim <= 0 ||
      !sk_size_mul((size_t)n, (size_t)dim, &base_elements) ||
      !sk_size_mul(base_elements, sizeof(float), &base_bytes)) {
    goto fail_res;
  }
  memset(&dset, 0, sizeof(dset));
  dset.dl_tensor.data = (void*)base;
  dset.dl_tensor.device.device_type = kDLCPU;
  dset.dl_tensor.device.device_id = 0;
  dset.dl_tensor.ndim = 2;
  dset.dl_tensor.dtype.code = kDLFloat; dset.dl_tensor.dtype.bits = 32; dset.dl_tensor.dtype.lanes = 1;
  dset.dl_tensor.shape = ds; dset.dl_tensor.strides = 0; dset.dl_tensor.byte_offset = 0;

  if (cuvsCagraIndexParamsCreate(&h->ip) != CUVS_SUCCESS) {
    goto fail_res;
  }
  h->ip->build_algo = NN_DESCENT;
  h->ip->graph_degree = 128;
  h->ip->intermediate_graph_degree = 256;
  h->ip->nn_descent_niter = 100;
  if (cuvsCagraIndexCreate(&h->idx)      != CUVS_SUCCESS) goto fail_params;
  if (cuvsCagraBuild(h->res, h->ip, &dset, h->idx) != CUVS_SUCCESS) goto fail_idx;
  if (pthread_mutex_init(&h->scratch_mu, NULL) != 0) goto fail_idx;
  h->scratch_mu_ready = 1;
  h->n = n; h->dim = dim;
  return h;

fail_idx:
  cuvsCagraIndexDestroy(h->idx);
fail_params:
  cuvsCagraIndexParamsDestroy(h->ip);
fail_res:
  cuvsResourcesDestroy(h->res); free(h);
  fprintf(stderr, "[seekdb_cuvs] build failed: %s\n", cuvsGetLastErrorText());
  return NULL;
}

int seekdb_cuvs_search(void* handle, const float* query, long nq, long topk,
                       unsigned int* out_ids, float* out_dist)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  if (!h || !query || !out_ids || nq <= 0 || topk <= 0 || topk > h->n || h->dim <= 0 ||
      !h->scratch_mu_ready) return 1;
  int rc = 0;
  size_t query_elements = 0;
  size_t query_bytes = 0;
  size_t result_count = 0;
  size_t result_bytes = 0;
  size_t result_ids_bytes = 0;
  size_t required_itopk = 0;
  if (!sk_size_mul((size_t)nq, (size_t)h->dim, &query_elements) ||
      !sk_size_mul(query_elements, sizeof(float), &query_bytes) ||
      !sk_size_mul((size_t)nq, (size_t)topk, &result_count) ||
      !sk_size_mul(result_count, sizeof(float), &result_bytes) ||
      !sk_size_mul(result_count, sizeof(unsigned int), &result_ids_bytes) ||
      !sk_size_mul((size_t)topk, 4, &required_itopk) || required_itopk > UINT32_MAX) return 2;
  if (pthread_mutex_lock(&h->scratch_mu) != 0) return 3;
  if (h->scratch_query_bytes < query_bytes) {
    float* next = NULL;
    if (cuvsRMMAlloc(h->res, (void**)&next, query_bytes) != CUVS_SUCCESS) { rc = 10; goto done; }
    if (h->scratch_query) cuvsRMMFree(h->res, h->scratch_query, h->scratch_query_bytes);
    h->scratch_query = next;
    h->scratch_query_bytes = query_bytes;
  }
  if (h->scratch_result_bytes < result_bytes) {
    unsigned int* next_ids = NULL;
    float* next_dist = NULL;
    if (cuvsRMMAlloc(h->res, (void**)&next_ids, result_ids_bytes) != CUVS_SUCCESS) { rc = 11; goto done; }
    if (cuvsRMMAlloc(h->res, (void**)&next_dist, result_bytes) != CUVS_SUCCESS) {
      cuvsRMMFree(h->res, next_ids, result_ids_bytes); rc = 12; goto done;
    }
    if (h->scratch_ids) cuvsRMMFree(h->res, h->scratch_ids, h->scratch_ids_bytes);
    if (h->scratch_dist) cuvsRMMFree(h->res, h->scratch_dist, h->scratch_result_bytes);
    h->scratch_ids = next_ids;
    h->scratch_dist = next_dist;
    h->scratch_ids_bytes = result_ids_bytes;
    h->scratch_result_bytes = result_bytes;
  }
  if (cudaMemcpy(h->scratch_query, query, query_bytes, cudaMemcpyDefault) != cudaSuccess) { rc = 13; goto done; }
  {
    DLManagedTensor qt, nt, dt; long qs[2]={nq,h->dim}, nsh[2]={nq,topk}, dsh[2]={nq,topk};
    memset(&qt, 0, sizeof(qt));
    qt.dl_tensor.data=h->scratch_query; qt.dl_tensor.device.device_type=kDLCUDA; qt.dl_tensor.device.device_id=0;
    qt.dl_tensor.ndim=2; qt.dl_tensor.dtype.code=kDLFloat; qt.dl_tensor.dtype.bits=32; qt.dl_tensor.dtype.lanes=1;
    qt.dl_tensor.shape=qs; qt.dl_tensor.strides=0; qt.dl_tensor.byte_offset=0;
    nt=qt; nt.dl_tensor.data=h->scratch_ids; nt.dl_tensor.dtype.code=kDLUInt; nt.dl_tensor.shape=nsh;
    dt=qt; dt.dl_tensor.data=h->scratch_dist; dt.dl_tensor.dtype.code=kDLFloat; dt.dl_tensor.shape=dsh;
    cuvsCagraSearchParams_t sp = 0;
    if (cuvsCagraSearchParamsCreate(&sp) != CUVS_SUCCESS) { rc=14; goto done; }
    if (required_itopk < 512) required_itopk = 512;
    if (sp->itopk_size < required_itopk) sp->itopk_size = required_itopk;
    sp->search_width = 4;
    cuvsFilter f; f.type=NO_FILTER; f.addr=(uintptr_t)0;
    if (cuvsCagraSearch(h->res, sp, h->idx, &qt, &nt, &dt, f) != CUVS_SUCCESS) { rc=15; cuvsCagraSearchParamsDestroy(sp); goto done; }
    if (cudaMemcpy(out_ids, h->scratch_ids, result_ids_bytes, cudaMemcpyDefault) != cudaSuccess) { rc=16; cuvsCagraSearchParamsDestroy(sp); goto done; }
    if (out_dist && cudaMemcpy(out_dist, h->scratch_dist, result_bytes, cudaMemcpyDefault) != cudaSuccess) rc=17;
    cuvsCagraSearchParamsDestroy(sp);
  }
done:
  pthread_mutex_unlock(&h->scratch_mu);
  if (rc) fprintf(stderr, "[seekdb_cuvs] search rc=%d: %s\n", rc, cuvsGetLastErrorText());
  return rc;
}

void seekdb_cuvs_free(void* handle)
{
  sk_cuvs_index* h = (sk_cuvs_index*)handle;
  if (!h) return;
  if (h->scratch_mu_ready) pthread_mutex_lock(&h->scratch_mu);
  if (h->scratch_query) cuvsRMMFree(h->res, h->scratch_query, h->scratch_query_bytes);
  if (h->scratch_ids) cuvsRMMFree(h->res, h->scratch_ids, h->scratch_ids_bytes);
  if (h->scratch_dist) cuvsRMMFree(h->res, h->scratch_dist, h->scratch_result_bytes);
  if (h->scratch_mu_ready) { pthread_mutex_unlock(&h->scratch_mu); pthread_mutex_destroy(&h->scratch_mu); }
  cuvsCagraIndexDestroy(h->idx);
  cuvsCagraIndexParamsDestroy(h->ip);
  cuvsResourcesDestroy(h->res);
  free(h);
}

int seekdb_cuvs_serialize(void* handle, const char* filename)
{
  sk_cuvs_index* index = (sk_cuvs_index*)handle;
  if (!index || !filename || !filename[0] || !index->scratch_mu_ready) return 1;
  if (pthread_mutex_lock(&index->scratch_mu) != 0) return 1;
  int result = cuvsCagraSerialize(index->res, filename, index->idx, true) != CUVS_SUCCESS;
  pthread_mutex_unlock(&index->scratch_mu);
  if (result) {
    fprintf(stderr, "[seekdb_cuvs] serialize failed: %s\n", cuvsGetLastErrorText());
    return 1;
  }
  return 0;
}

void* seekdb_cuvs_deserialize(const char* filename, long n, long dim)
{
  size_t elements = 0;
  size_t bytes = 0;
  if (!filename || !filename[0] || n <= 0 || (uint64_t)n > UINT32_MAX || dim <= 0 ||
      !sk_size_mul((size_t)n, (size_t)dim, &elements) ||
      !sk_size_mul(elements, sizeof(float), &bytes)) return NULL;
  sk_cuvs_index* index = (sk_cuvs_index*)calloc(1, sizeof(*index));
  if (!index) return NULL;
  if (cuvsResourcesCreate(&index->res) != CUVS_SUCCESS) goto fail;
  if (cuvsCagraIndexParamsCreate(&index->ip) != CUVS_SUCCESS) goto fail_res;
  if (cuvsCagraIndexCreate(&index->idx) != CUVS_SUCCESS) goto fail_ip;
  if (cuvsCagraDeserialize(index->res, filename, index->idx) != CUVS_SUCCESS) goto fail_idx;
  {
    int64_t actual_n = 0;
    int64_t actual_dim = 0;
    if (cuvsCagraIndexGetSize(index->idx, &actual_n) != CUVS_SUCCESS ||
        cuvsCagraIndexGetDims(index->idx, &actual_dim) != CUVS_SUCCESS ||
        actual_n != n || actual_dim != dim) {
      fprintf(stderr, "[seekdb_cuvs] snapshot shape mismatch: %ld x %ld, expected %ld x %ld\n",
              (long)actual_n, (long)actual_dim, n, dim);
      goto fail_idx;
    }
  }
  if (pthread_mutex_init(&index->scratch_mu, NULL) != 0) goto fail_idx;
  index->scratch_mu_ready = 1;
  index->n = n;
  index->dim = dim;
  return index;
fail_idx:
  if (index->scratch_mu_ready) {
    pthread_mutex_destroy(&index->scratch_mu);
    index->scratch_mu_ready = 0;
  }
  cuvsCagraIndexDestroy(index->idx);
fail_ip:
  cuvsCagraIndexParamsDestroy(index->ip);
fail_res:
  cuvsResourcesDestroy(index->res);
fail:
  fprintf(stderr, "[seekdb_cuvs] deserialize failed: %s\n", cuvsGetLastErrorText());
  free(index);
  return NULL;
}

int seekdb_cuvs_cagra_knn(const float* base, long n, long dim,
                          const float* query, long nq, long topk,
                          unsigned int* out_ids)
{
  void* h = seekdb_cuvs_build(base, n, dim);
  if (!h) return 10;
  int rc = seekdb_cuvs_search(h, query, nq, topk, out_ids, NULL);
  seekdb_cuvs_free(h);
  return rc;
}
