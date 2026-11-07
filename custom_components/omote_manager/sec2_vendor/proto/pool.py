"""Independent protobuf descriptor pool for bundled ESP-IDF schemas.

Never register generic 'session.proto' names in Home Assistant's global pool.
"""
from google.protobuf.descriptor_pool import DescriptorPool

POOL = DescriptorPool()
