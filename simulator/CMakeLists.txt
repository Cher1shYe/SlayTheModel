cmake_minimum_required(VERSION 3.19)
project(sts2_sim VERSION 0.1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    add_compile_options(/O2 /EHsc /bigobj /W3)
else()
    add_compile_options(-O3 -Wno-shift-count-overflow)
endif()

file(GLOB_RECURSE STS2_SOURCES CONFIGURE_DEPENDS "src/*.cpp")
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_subdirectory(pybind11)
pybind11_add_module(sts2_sim bindings/bindings.cpp ${STS2_SOURCES})
target_include_directories(sts2_sim PRIVATE include)
# importable straight from simulator/ by agent/common.py
set_target_properties(sts2_sim PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

add_executable(sts2_bench apps/bench.cpp ${STS2_SOURCES})
target_include_directories(sts2_bench PRIVATE include)
set_target_properties(sts2_bench PROPERTIES
    OUTPUT_NAME bench
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

if(NOT MSVC)
    # no MinGW runtime DLLs needed next to the module / bench binary
    target_link_options(sts2_sim PRIVATE -static-libgcc -static-libstdc++)
    target_link_options(sts2_bench PRIVATE -static-libgcc -static-libstdc++)
endif()
