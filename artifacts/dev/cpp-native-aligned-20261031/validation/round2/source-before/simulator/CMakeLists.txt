cmake_minimum_required(VERSION 3.19)
project(sts2_sim VERSION 0.1 LANGUAGES CXX)
include(CTest)

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
# Importable straight from simulator/ by default. An explicit output directory
# allows testing a new extension without replacing one used by live training.
set(STS2_MODULE_OUTPUT_DIR "${CMAKE_CURRENT_SOURCE_DIR}" CACHE PATH
    "Output directory for the Python extension")
set_target_properties(sts2_sim PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${STS2_MODULE_OUTPUT_DIR}"
    RUNTIME_OUTPUT_DIRECTORY "${STS2_MODULE_OUTPUT_DIR}")

add_executable(sts2_bench apps/bench.cpp ${STS2_SOURCES})
target_include_directories(sts2_bench PRIVATE include)
set_target_properties(sts2_bench PROPERTIES
    OUTPUT_NAME bench
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

# Native rule regressions (run by tests/test_native_rules.py).
add_executable(sts2_rules_test tests/rules_regression.cpp ${STS2_SOURCES})
target_include_directories(sts2_rules_test PRIVATE include)
set_target_properties(sts2_rules_test PROPERTIES
    OUTPUT_NAME rules_test
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

# Public observation collision regressions.
add_executable(sts2_observation_test tests/observation_contract.cpp ${STS2_SOURCES})
target_include_directories(sts2_observation_test PRIVATE include)
set_target_properties(sts2_observation_test PROPERTIES
    OUTPUT_NAME observation_test
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

add_executable(sts2_relic_contract_test tests/relic_contract.cpp ${STS2_SOURCES})
target_include_directories(sts2_relic_contract_test PRIVATE include)
set_target_properties(sts2_relic_contract_test PROPERTIES
    OUTPUT_NAME relic_contract_test
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

if(BUILD_TESTING)
    add_test(NAME simulator_rules COMMAND sts2_rules_test)
    add_test(NAME simulator_observation COMMAND sts2_observation_test)
    add_test(NAME simulator_relics COMMAND sts2_relic_contract_test)
endif()

if(BUILD_TESTING)
    add_executable(sts2_enchantment_test tests/enchantment_contract.cpp ${STS2_SOURCES})
    target_include_directories(sts2_enchantment_test PRIVATE include)
    add_test(NAME enchantment_contract COMMAND sts2_enchantment_test)
    add_executable(sts2_monster_audit_test tests/monster_audit_regression.cpp ${STS2_SOURCES})
    target_include_directories(sts2_monster_audit_test PRIVATE include)
    add_test(NAME monster_audit COMMAND sts2_monster_audit_test)

    add_executable(sts2_map_event_audit_test tests/map_event_audit_regression.cpp ${STS2_SOURCES})
    target_include_directories(sts2_map_event_audit_test PRIVATE include)
    add_test(NAME map_event_audit COMMAND sts2_map_event_audit_test)

    add_executable(sts2_snapshot_validation_test tests/snapshot_validation.cpp ${STS2_SOURCES})
    target_include_directories(sts2_snapshot_validation_test PRIVATE include)
    # Assertions in this regression are required even in Release builds.
    if(MSVC)
        target_compile_options(sts2_snapshot_validation_test PRIVATE /UNDEBUG)
    else()
        target_compile_options(sts2_snapshot_validation_test PRIVATE -UNDEBUG)
    endif()
    add_test(NAME snapshot_validation COMMAND sts2_snapshot_validation_test)

    add_executable(sts2_scroll_boxes_test tests/scroll_boxes_regression.cpp ${STS2_SOURCES})
    target_include_directories(sts2_scroll_boxes_test PRIVATE include)
    if(MSVC)
        target_compile_options(sts2_scroll_boxes_test PRIVATE /UNDEBUG)
    else()
        target_compile_options(sts2_scroll_boxes_test PRIVATE -UNDEBUG)
    endif()
    add_test(NAME scroll_boxes COMMAND sts2_scroll_boxes_test)

    add_executable(sts2_mcts_test tests/mcts_regression.cpp ${STS2_SOURCES})
    target_include_directories(sts2_mcts_test PRIVATE include)
    if(MSVC)
        target_compile_options(sts2_mcts_test PRIVATE /UNDEBUG)
    else()
        target_compile_options(sts2_mcts_test PRIVATE -UNDEBUG)
        if(MINGW)
            target_link_options(sts2_mcts_test PRIVATE -static-libgcc -static-libstdc++)
        endif()
    endif()
    add_test(NAME mcts COMMAND sts2_mcts_test)

    add_executable(sts2_hidden_resampling_test tests/hidden_resampling.cpp ${STS2_SOURCES})
    target_include_directories(sts2_hidden_resampling_test PRIVATE include)
    if(MINGW)
        target_link_options(sts2_hidden_resampling_test PRIVATE -static-libgcc -static-libstdc++)
    endif()
    add_test(NAME hidden_resampling COMMAND sts2_hidden_resampling_test)
endif()

if(MINGW)
    # no MinGW runtime DLLs needed next to the module / bench binary
    target_link_options(sts2_sim PRIVATE -static-libgcc -static-libstdc++)
    target_link_options(sts2_bench PRIVATE -static-libgcc -static-libstdc++)
    target_link_options(sts2_rules_test PRIVATE -static-libgcc -static-libstdc++)
    target_link_options(sts2_observation_test PRIVATE -static-libgcc -static-libstdc++)
    target_link_options(sts2_relic_contract_test PRIVATE -static-libgcc -static-libstdc++)
    if(BUILD_TESTING)
        target_link_options(sts2_enchantment_test PRIVATE -static-libgcc -static-libstdc++)
        target_link_options(sts2_monster_audit_test PRIVATE -static-libgcc -static-libstdc++)
        target_link_options(sts2_map_event_audit_test PRIVATE -static-libgcc -static-libstdc++)
        target_link_options(sts2_snapshot_validation_test PRIVATE -static-libgcc -static-libstdc++)
        target_link_options(sts2_scroll_boxes_test PRIVATE -static-libgcc -static-libstdc++)
    endif()
endif()

if(BUILD_TESTING)
    foreach(fixture native_card_alignment native_rng_contract native_run_alignment native_seed_integration)
        if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tests/${fixture}.cpp")
            add_executable(sts2_${fixture}_test tests/${fixture}.cpp ${STS2_SOURCES})
            target_include_directories(sts2_${fixture}_test PRIVATE include json/include)
            add_test(NAME ${fixture} COMMAND sts2_${fixture}_test)
        endif()
    endforeach()
    # Every regression needs active assertions, including Release builds.
    get_directory_property(sts2_targets BUILDSYSTEM_TARGETS)
    foreach(target IN LISTS sts2_targets)
        if(target MATCHES "_test$")
            if(MSVC)
                target_compile_options(${target} PRIVATE /UNDEBUG)
            else()
                target_compile_options(${target} PRIVATE -UNDEBUG)
            endif()
        endif()
    endforeach()
endif()
